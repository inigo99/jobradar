"""SQLite persistence.

One file, ``data/jobradar.sqlite3``, holds everything: the user's settings and
profile, every job ever collected, the user's tracking state, generated
documents and a log of pipeline runs. A single store means the CLI and the
dashboard can never disagree about what the configuration is.

Two design rules are enforced here and worth knowing about:

1. **Jobs are appended, never replaced.** A job that disappears from a board is
   marked ``closed``; it is not deleted, because the user's tracking record for
   it would be orphaned and the job would reappear as new next week.
2. **The pipeline never writes to ``applications``.** That table belongs to the
   user. Search runs may update job data around it, but the triage state, the
   stage and the notes are only ever written from the dashboard or the CLI at
   the user's request.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import Paths, Settings, validation_summary
from .errors import ConfigError, StorageError, describe_os_error
from .models import (
    AnswerThread,
    Application,
    ApplicationStatus,
    BankEntry,
    GeneratedDocument,
    Job,
    MailNews,
    MatchScore,
    Profile,
    SearchRun,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Settings and profile are stored as JSON documents so the Pydantic models
-- remain the schema of record and adding a field needs no migration.
CREATE TABLE IF NOT EXISTS documents_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    native_id    TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    company      TEXT,
    title        TEXT,
    posted_at    TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    closed       INTEGER NOT NULL DEFAULT 0,
    closed_reason TEXT DEFAULT '',
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS idx_jobs_closed ON jobs(closed);

CREATE TABLE IF NOT EXISTS matches (
    job_id   TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    tailored REAL NOT NULL DEFAULT 0,
    payload  TEXT NOT NULL
);

-- Owned by the user. The pipeline must not write here.
CREATE TABLE IF NOT EXISTS applications (
    job_id     TEXT PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'active',
    stage      TEXT,
    applied_on TEXT,
    notes      TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_documents (
    job_id  TEXT NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (job_id, kind)
);

-- Jobs withdrawn because the ad closed. Consulted before re-adding anything.
CREATE TABLE IF NOT EXISTS closed_jobs (
    job_id    TEXT PRIMARY KEY,
    company   TEXT,
    title     TEXT,
    reason    TEXT,
    closed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL
);

-- Jobs a filter rejected. Kept, not discarded: a filter one notch too strict
-- is invisible when its victims vanish, and "the board is empty" and "the
-- salary floor is eating everything" look identical from the outside. The
-- whole job is stored so it can be read, judged and restored.
CREATE TABLE IF NOT EXISTS filtered_jobs (
    id          TEXT PRIMARY KEY,
    company     TEXT,
    title       TEXT,
    source      TEXT,
    posted_at   TEXT,
    reason      TEXT NOT NULL,
    reason_shape TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'other',
    filtered_at TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filtered_category ON filtered_jobs(category);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _shape_of(reason: str) -> str:
    """Reason with its numbers blanked, for grouping. Imported late to avoid a
    circular import between storage and the pipeline."""
    from .pipeline.filters import shape

    return shape(reason)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load(raw: str, what: str) -> Any:
    """Decode a stored JSON payload, naming what it was if it is corrupt."""
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise StorageError(
            f"The stored {what} is corrupt and cannot be read.",
            hint="Restore the database from a backup, or delete that record.",
        ) from exc


def _model(model: Any, payload: str, what: str) -> Any:
    """Decode and validate one stored record of type ``model``."""
    try:
        return model.model_validate(_load(payload, what))
    except ValidationError as exc:
        raise StorageError(
            f"The stored {what} is invalid: {validation_summary(exc)}",
            hint="Restore the database from a backup, or regenerate that record.",
        ) from exc


def _url_of(payload: str) -> str:
    """The ``url`` field of a stored job, or "" if the payload is damaged."""
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return ""
    return str(data.get("url", "")) if isinstance(data, dict) else ""


def _storage_error(exc: sqlite3.Error, path: Path) -> StorageError:
    """Turn a SQLite exception into a message that says what to do."""
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return StorageError(
            f"The database {path} is locked by another process.",
            hint="Wait for the other JobRadar command (or the dashboard's search) to finish.",
        )
    if "readonly" in text or "read-only" in text:
        return StorageError(
            f"The database {path} is read-only.",
            hint="Check the permissions of the data directory.",
        )
    if "disk" in text and ("full" in text or "i/o" in text):
        return StorageError(
            f"Could not write to the database {path}: {exc}.",
            hint="Free some disk space and try again.",
        )
    if "not a database" in text or "malformed" in text or "corrupt" in text:
        return StorageError(
            f"The database {path} is damaged: {exc}.",
            hint="Restore it from a backup, or move it aside to start afresh.",
        )
    if "unable to open" in text:
        return StorageError(
            f"Cannot open the database {path}.",
            hint="Check that the data directory exists and that you can write to it.",
        )
    return StorageError(f"Database error on {path}: {exc}.")


class Database:
    """Thin, dependency-free wrapper around the SQLite file, one connection per thread."""

    def __init__(self, paths: Paths | None = None, path: str | Path | None = None):
        self.paths = paths or Paths.resolve()
        self.paths.ensure()
        self.path = Path(path) if path else self.paths.db
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"Cannot create {self.path.parent}: {describe_os_error(exc)}.",
                hint="Point --home (or JOBRADAR_HOME) at a folder you can write to.",
            ) from exc
        if self.path.is_dir():
            raise StorageError(
                f"{self.path} is a directory, not a database file.",
                hint="Move it aside or choose another data directory.",
            )
        self._local = threading.local()
        # Every connection ever opened, whichever thread opened it, so
        # ``close`` can release them all and not just the caller's own.
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._migrate()

    def _get_conn(self) -> sqlite3.Connection:
        """This thread's connection, opened on first use.

        One connection per thread: the dashboard runs searches in a worker
        thread while the page keeps reading, and a shared connection would
        interleave their transactions.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            try:
                conn = sqlite3.connect(self.path, timeout=20.0, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.Error as exc:
                raise _storage_error(exc, self.path) from exc
            self._local.conn = conn
            with self._connections_lock:
                self._connections.append(conn)
        return conn

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        """Run a read query, reporting SQLite failures as :class:`StorageError`."""
        try:
            return self._get_conn().execute(sql, tuple(params))
        except sqlite3.Error as exc:
            raise _storage_error(exc, self.path) from exc

    # -- lifecycle ---------------------------------------------------------

    def _migrate(self) -> None:
        with self.transaction() as cursor:
            cursor.executescript(SCHEMA)
            cursor.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise _storage_error(exc, self.path) from exc
        except BaseException:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def close(self) -> None:
        """Close every connection this object opened, in any thread."""
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error as exc:  # closing must never raise
                log.debug("Could not close a database connection: %s", exc)
        self._local = threading.local()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- key/value documents (settings, profile) ---------------------------

    def _get_doc(self, key: str) -> dict | None:
        row = self._execute(
            "SELECT value FROM documents_kv WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        data = _load(row["value"], key)
        if not isinstance(data, dict):
            raise StorageError(
                f"The stored {key} is not a JSON object.",
                hint="Restore the database from a backup, or set it up again.",
            )
        return data

    def _put_doc(self, key: str, value: dict) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "INSERT INTO documents_kv(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, _json(value)),
            )

    def load_settings(self) -> Settings:
        """Current settings, or freshly defaulted ones on a blank install."""
        data = self._get_doc("settings")
        if not data:
            return Settings()
        try:
            return Settings.validated(data, origin="stored settings")
        except ConfigError as exc:
            exc.hint = "Save the settings again from the dashboard, or rerun 'jobradar init'."
            raise

    def save_settings(self, settings: Settings) -> None:
        self._put_doc("settings", settings.model_dump(mode="json"))

    def load_profile(self) -> Profile | None:
        data = self._get_doc("profile")
        if not data:
            return None
        try:
            return Profile.model_validate(data)
        except ValidationError as exc:
            raise StorageError(
                f"The stored profile is invalid: {validation_summary(exc)}",
                hint="Import your CV again with 'jobradar init --cv <file>'.",
            ) from exc

    def save_profile(self, profile: Profile) -> None:
        self._put_doc("profile", profile.model_dump(mode="json"))

    # -- jobs ---------------------------------------------------------------

    def upsert_jobs(self, jobs: Iterable[Job]) -> tuple[int, int]:
        """Insert new jobs and refresh ``last_seen`` on ones already known.

        Returns ``(new, updated)``. Existing rows keep their ``first_seen`` so
        the "new today" view stays meaningful.
        """
        new = updated = 0
        now = _now()
        with self.transaction() as cursor:
            for job in jobs:
                job.ensure_id()
                exists = cursor.execute(
                    "SELECT 1 FROM jobs WHERE id = ?", (job.id,)
                ).fetchone()
                payload = _json(job.model_dump(mode="json"))
                if exists:
                    cursor.execute(
                        "UPDATE jobs SET last_seen = ?, payload = ?, closed = 0, "
                        "closed_reason = '' WHERE id = ?",
                        (now, payload, job.id),
                    )
                    updated += 1
                else:
                    cursor.execute(
                        "INSERT INTO jobs(id, source, native_id, fingerprint, company, "
                        "title, posted_at, first_seen, last_seen, closed, closed_reason, payload) "
                        "VALUES (?,?,?,?,?,?,?,?,?,0,'',?)",
                        (
                            job.id,
                            job.source,
                            job.native_id,
                            job.fingerprint(),
                            job.company or "",
                            job.title or "",
                            job.posted_at.isoformat() if job.posted_at else None,
                            now,
                            now,
                            payload,
                        ),
                    )
                    new += 1
        return new, updated

    def get_job(self, job_id: str) -> Job | None:
        row = self._execute(
            "SELECT payload, first_seen, last_seen, closed, closed_reason FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(
        self, include_closed: bool = False, limit: int | None = None, offset: int = 0
    ) -> list[Job]:
        sql = "SELECT payload, first_seen, last_seen, closed, closed_reason FROM jobs"
        params: list[Any] = []
        if not include_closed:
            sql += " WHERE closed = 0"
        sql += " ORDER BY first_seen DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        jobs: list[Job] = []
        for row in self._execute(sql, params):
            # One damaged row must not hide the whole board: skip it, loudly.
            try:
                jobs.append(self._row_to_job(row))
            except StorageError as exc:
                log.warning("Skipping a stored job: %s", exc)
        return jobs

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        data = _load(row["payload"], "job")
        try:
            job = Job.model_validate(data)
        except ValidationError as exc:
            job_id = data.get("id", "?") if isinstance(data, dict) else "?"
            raise StorageError(
                f"The stored job {job_id} is invalid: {validation_summary(exc)}",
                hint="Run the search again; the job will be re-read from its board.",
            ) from exc
        job.closed = bool(row["closed"])
        job.closed_reason = row["closed_reason"] or ""
        return job

    def known_job_ids(self) -> set[str]:
        return {r["id"] for r in self._execute("SELECT id FROM jobs")}

    def known_fingerprints(self) -> dict[str, str]:
        """fingerprint -> job id, for cross-source duplicate detection."""
        return {
            r["fingerprint"]: r["id"]
            for r in self._execute("SELECT id, fingerprint FROM jobs")
        }

    def mark_closed(self, job_id: str, reason: str) -> None:
        """Record that an ad no longer accepts applications.

        The job row is kept so any tracking record stays attached to it; only
        the dashboard's *active* view hides it.
        """
        job = self.get_job(job_id)
        with self.transaction() as cursor:
            cursor.execute(
                "UPDATE jobs SET closed = 1, closed_reason = ? WHERE id = ?", (reason, job_id)
            )
            cursor.execute(
                "INSERT INTO closed_jobs(job_id, company, title, reason, closed_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET reason = excluded.reason",
                (
                    job_id,
                    (job.company or "") if job else "",
                    (job.title or "") if job else "",
                    reason,
                    _now(),
                ),
            )

    def closed_job_ids(self) -> set[str]:
        """Ids that must never be re-added by a later search run."""
        return {r["job_id"] for r in self._execute("SELECT job_id FROM closed_jobs")}

    # -- filtered-out jobs --------------------------------------------------

    def save_filtered(self, entries: Iterable[tuple[Job, str, str]]) -> int:
        """Record jobs a filter rejected, with the reason and its shape.

        Re-running a search re-rejects the same ads, so this is an upsert
        keyed on the job id: the list is "what the current configuration is
        costing you", not a log that grows forever.
        """
        rows = 0
        with self.transaction() as cursor:
            for job, reason, category in entries:
                cursor.execute(
                    "INSERT INTO filtered_jobs(id, company, title, source, posted_at, "
                    "reason, reason_shape, category, filtered_at, payload) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET reason = excluded.reason, "
                    "reason_shape = excluded.reason_shape, category = excluded.category, "
                    "filtered_at = excluded.filtered_at, payload = excluded.payload",
                    (
                        job.id, job.company or "", job.title or "", job.source or "",
                        job.posted_at.isoformat() if job.posted_at else None,
                        reason, _shape_of(reason), category, _now(),
                        _json(job.model_dump(mode="json")),
                    ),
                )
                rows += 1
        return rows

    def list_filtered(self, limit: int = 500) -> list[dict[str, Any]]:
        """Everything a filter rejected, most recent first."""
        return [
            {
                "id": r["id"], "company": r["company"], "title": r["title"],
                "source": r["source"], "posted_at": r["posted_at"],
                "reason": r["reason"], "reason_shape": r["reason_shape"],
                "category": r["category"], "filtered_at": r["filtered_at"],
                "url": _url_of(r["payload"]),
            }
            for r in self._execute(
                "SELECT * FROM filtered_jobs ORDER BY filtered_at DESC, company LIMIT ?",
                (limit,),
            )
        ]

    def filtered_tally(self) -> dict[str, list[tuple[str, int]]]:
        """Counts by coarse category and by the exact shape of the reason.

        The categories say which filter to reach for; the shapes say what it is
        actually rejecting. One without the other is half an answer.
        """
        by_category = [
            (r["category"], r["n"])
            for r in self._execute(
                "SELECT category, COUNT(*) AS n FROM filtered_jobs "
                "GROUP BY category ORDER BY n DESC"
            )
        ]
        by_shape = [
            (r["reason_shape"], r["n"])
            for r in self._execute(
                "SELECT reason_shape, COUNT(*) AS n FROM filtered_jobs "
                "GROUP BY reason_shape ORDER BY n DESC LIMIT 12"
            )
        ]
        return {"by_category": by_category, "by_shape": by_shape}

    def get_filtered_job(self, job_id: str) -> Job | None:
        row = self._execute(
            "SELECT payload FROM filtered_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return self._row_to_job_payload(row["payload"]) if row else None

    @staticmethod
    def _row_to_job_payload(payload: str) -> Job:
        data = _load(payload, "filtered job")
        try:
            return Job.model_validate(data)
        except ValidationError as exc:
            raise StorageError(
                f"The stored filtered job is invalid: {validation_summary(exc)}",
                hint="Empty the filtered list with 'jobradar filtered --clear'.",
            ) from exc

    def restore_filtered(self, job_id: str) -> Job | None:
        """Move one rejected job back onto the board.

        The filter that rejected it still exists, so a later run would reject
        it again; the point is that the decision is now the user's and visible,
        not a silent drop.
        """
        job = self.get_filtered_job(job_id)
        if job is None:
            return None
        self.upsert_jobs([job])
        self.drop_filtered([job_id])
        return job

    def drop_filtered(self, job_ids: Iterable[str]) -> None:
        with self.transaction() as cursor:
            for job_id in job_ids:
                cursor.execute("DELETE FROM filtered_jobs WHERE id = ?", (job_id,))

    def clear_filtered(self) -> None:
        with self.transaction() as cursor:
            cursor.execute("DELETE FROM filtered_jobs")

    # -- match scores -------------------------------------------------------

    def save_score(self, job_id: str, score: MatchScore) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "INSERT INTO matches(job_id, tailored, payload) VALUES (?,?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET tailored = excluded.tailored, "
                "payload = excluded.payload",
                (job_id, score.tailored, _json(score.model_dump(mode="json"))),
            )

    def get_score(self, job_id: str) -> MatchScore | None:
        row = self._execute(
            "SELECT payload FROM matches WHERE job_id = ?", (job_id,)
        ).fetchone()
        return _model(MatchScore, row["payload"], "match score") if row else None

    def all_scores(self) -> dict[str, MatchScore]:
        return {
            r["job_id"]: _model(MatchScore, r["payload"], "match score")
            for r in self._execute("SELECT job_id, payload FROM matches")
        }

    # -- applications (user-owned) -----------------------------------------

    def get_application(self, job_id: str) -> Application:
        row = self._execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        if not row:
            return Application(job_id=job_id)
        try:
            return Application(
                job_id=row["job_id"],
                status=ApplicationStatus(row["status"]),
                stage=row["stage"] or None,
                applied_on=date.fromisoformat(row["applied_on"]) if row["applied_on"] else None,
                notes=row["notes"] or "",
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        except (ValueError, ValidationError) as exc:
            raise StorageError(
                f"The tracking record for job {job_id} is invalid: {exc}",
                hint="Set its status again from the dashboard.",
            ) from exc

    def all_applications(self) -> dict[str, Application]:
        result: dict[str, Application] = {}
        for row in self._execute("SELECT job_id FROM applications"):
            result[row["job_id"]] = self.get_application(row["job_id"])
        return result

    def save_application(self, application: Application) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "INSERT INTO applications(job_id, status, stage, applied_on, notes, updated_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET "
                "status = excluded.status, stage = excluded.stage, "
                "applied_on = excluded.applied_on, notes = excluded.notes, "
                "updated_at = excluded.updated_at",
                (
                    application.job_id,
                    application.status.value,
                    application.stage.value if application.stage else None,
                    application.applied_on.isoformat() if application.applied_on else None,
                    application.notes,
                    _now(),
                ),
            )

    def tracked_job_ids(self) -> set[str]:
        """Jobs the user has touched — these are never removed automatically."""
        return {r["job_id"] for r in self._execute("SELECT job_id FROM applications")}

    # -- generated documents ------------------------------------------------

    def save_document(self, document: GeneratedDocument) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "INSERT INTO generated_documents(job_id, kind, payload) VALUES (?,?,?) "
                "ON CONFLICT(job_id, kind) DO UPDATE SET payload = excluded.payload",
                (document.job_id, document.kind, _json(document.model_dump(mode="json"))),
            )

    def get_document(self, job_id: str, kind: str) -> GeneratedDocument | None:
        row = self._execute(
            "SELECT payload FROM generated_documents WHERE job_id = ? AND kind = ?",
            (job_id, kind),
        ).fetchone()
        return _model(GeneratedDocument, row["payload"], "document") if row else None

    def documents_for(self, job_id: str) -> dict[str, GeneratedDocument]:
        rows = self._execute(
            "SELECT kind, payload FROM generated_documents WHERE job_id = ?", (job_id,)
        )
        return {
            r["kind"]: _model(GeneratedDocument, r["payload"], "document") for r in rows
        }

    # -- mail ---------------------------------------------------------------
    # News and orphans are small and rewritten whole on each check, so they
    # live in the key/value table rather than tables of their own.

    def mail_news(self) -> dict[str, MailNews]:
        """The latest reply per job id."""
        data = self._get_doc("mail_news") or {}
        news: dict[str, MailNews] = {}
        for job_id, payload in data.items():
            try:
                news[job_id] = MailNews.model_validate(payload)
            except ValidationError as exc:
                log.warning("Skipping stored mail news for %s: %s", job_id, exc)
        return news

    def save_mail_news(self, items: Iterable[MailNews]) -> None:
        """Merge new replies in, keeping the newest one per job."""
        current = self.mail_news()
        for item in items:
            known = current.get(item.job_id)
            if known is None or item.received_at >= known.received_at:
                current[item.job_id] = item
        self._put_doc("mail_news", {k: v.model_dump(mode="json") for k, v in current.items()})

    def mail_orphans(self) -> list[MailNews]:
        data = self._get_doc("mail_orphans") or {}
        orphans: list[MailNews] = []
        for payload in data.get("items", []):
            try:
                orphans.append(MailNews.model_validate(payload))
            except ValidationError as exc:
                log.warning("Skipping a stored unmatched mail: %s", exc)
        return orphans

    def save_mail_orphans(self, items: Iterable[MailNews], keep: int = 50) -> None:
        """Merge by message id, newest first, keeping the most recent ``keep``."""
        merged = {o.message_id or o.subject: o for o in self.mail_orphans()}
        for item in items:
            merged[item.message_id or item.subject] = item
        ordered = sorted(merged.values(), key=lambda o: o.received_at, reverse=True)[:keep]
        self._put_doc("mail_orphans", {"items": [o.model_dump(mode="json") for o in ordered]})

    def mail_checked_on(self) -> date | None:
        data = self._get_doc("mail_state") or {}
        try:
            return date.fromisoformat(data["checked_on"]) if data.get("checked_on") else None
        except ValueError:
            return None

    def set_mail_checked_on(self, day: date) -> None:
        self._put_doc("mail_state", {"checked_on": day.isoformat()})

    # -- form answers and the answer bank ------------------------------------

    def answer_thread(self, job_id: str) -> AnswerThread:
        """The job's form-answer thread (empty when none was started)."""
        data = self._get_doc(f"answers:{job_id}")
        if not data:
            return AnswerThread(job_id=job_id)
        try:
            return AnswerThread.model_validate(data)
        except ValidationError as exc:
            raise StorageError(
                f"The stored form answers for job {job_id} are unreadable: {exc.errors()[0]['msg']}.",
                hint="Clear the thread from the dashboard to start it again.",
            ) from exc

    def save_answer_thread(self, thread: AnswerThread) -> None:
        self._put_doc(f"answers:{thread.job_id}", thread.model_dump(mode="json"))

    def delete_answer_thread(self, job_id: str) -> None:
        with self.transaction() as cursor:
            cursor.execute("DELETE FROM documents_kv WHERE key = ?", (f"answers:{job_id}",))

    def answer_bank(self) -> list[BankEntry]:
        """Saved answers, newest first."""
        data = self._get_doc("answer_bank") or {}
        entries: list[BankEntry] = []
        for payload in data.get("items", []):
            try:
                entries.append(BankEntry.model_validate(payload))
            except ValidationError as exc:
                log.warning("Skipping an unreadable answer-bank entry: %s", exc)
        return sorted(entries, key=lambda e: e.saved_at, reverse=True)

    def save_answer_bank(self, entries: Iterable[BankEntry]) -> None:
        self._put_doc("answer_bank", {"items": [e.model_dump(mode="json") for e in entries]})

    # -- run log ------------------------------------------------------------

    def log_run(self, run: SearchRun) -> None:
        with self.transaction() as cursor:
            cursor.execute("INSERT INTO runs(payload) VALUES (?)", (_json(run.model_dump(mode="json")),))

    def recent_runs(self, limit: int = 20) -> list[SearchRun]:
        rows = self._execute(
            "SELECT payload FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [_model(SearchRun, r["payload"], "search run") for r in rows]
