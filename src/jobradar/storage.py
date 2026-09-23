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
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .config import Paths, Settings
from .models import (
    Application,
    ApplicationStatus,
    GeneratedDocument,
    Job,
    MatchScore,
    Profile,
    SearchRun,
)

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


class Database:
    """Thin, dependency-free wrapper around the SQLite file."""

    def __init__(self, paths: Paths | None = None, path: str | Path | None = None):
        self.paths = paths or Paths.resolve()
        self.paths.ensure()
        self.path = Path(path) if path else self.paths.db
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

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
        cursor = self.connection.cursor()
        try:
            yield cursor
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- key/value documents (settings, profile) ---------------------------

    def _get_doc(self, key: str) -> dict | None:
        row = self.connection.execute(
            "SELECT value FROM documents_kv WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row["value"]) if row else None

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
        return Settings.model_validate(data) if data else Settings()

    def save_settings(self, settings: Settings) -> None:
        self._put_doc("settings", settings.model_dump(mode="json"))

    def load_profile(self) -> Profile | None:
        data = self._get_doc("profile")
        return Profile.model_validate(data) if data else None

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
        row = self.connection.execute(
            "SELECT payload, first_seen, last_seen, closed, closed_reason FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, include_closed: bool = False) -> list[Job]:
        sql = "SELECT payload, first_seen, last_seen, closed, closed_reason FROM jobs"
        if not include_closed:
            sql += " WHERE closed = 0"
        return [self._row_to_job(row) for row in self.connection.execute(sql)]

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        job = Job.model_validate(json.loads(row["payload"]))
        job.closed = bool(row["closed"])
        job.closed_reason = row["closed_reason"] or ""
        return job

    def known_job_ids(self) -> set[str]:
        return {r["id"] for r in self.connection.execute("SELECT id FROM jobs")}

    def known_fingerprints(self) -> dict[str, str]:
        """fingerprint -> job id, for cross-source duplicate detection."""
        return {
            r["fingerprint"]: r["id"]
            for r in self.connection.execute("SELECT id, fingerprint FROM jobs")
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
        return {r["job_id"] for r in self.connection.execute("SELECT job_id FROM closed_jobs")}

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
                "url": json.loads(r["payload"]).get("url", ""),
            }
            for r in self.connection.execute(
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
            for r in self.connection.execute(
                "SELECT category, COUNT(*) AS n FROM filtered_jobs "
                "GROUP BY category ORDER BY n DESC"
            )
        ]
        by_shape = [
            (r["reason_shape"], r["n"])
            for r in self.connection.execute(
                "SELECT reason_shape, COUNT(*) AS n FROM filtered_jobs "
                "GROUP BY reason_shape ORDER BY n DESC LIMIT 12"
            )
        ]
        return {"by_category": by_category, "by_shape": by_shape}

    def get_filtered_job(self, job_id: str) -> Job | None:
        row = self.connection.execute(
            "SELECT payload FROM filtered_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return Job.model_validate(json.loads(row["payload"])) if row else None

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
        row = self.connection.execute(
            "SELECT payload FROM matches WHERE job_id = ?", (job_id,)
        ).fetchone()
        return MatchScore.model_validate(json.loads(row["payload"])) if row else None

    def all_scores(self) -> dict[str, MatchScore]:
        return {
            r["job_id"]: MatchScore.model_validate(json.loads(r["payload"]))
            for r in self.connection.execute("SELECT job_id, payload FROM matches")
        }

    # -- applications (user-owned) -----------------------------------------

    def get_application(self, job_id: str) -> Application:
        row = self.connection.execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        if not row:
            return Application(job_id=job_id)
        return Application(
            job_id=row["job_id"],
            status=ApplicationStatus(row["status"]),
            stage=row["stage"] or None,
            applied_on=date.fromisoformat(row["applied_on"]) if row["applied_on"] else None,
            notes=row["notes"] or "",
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def all_applications(self) -> dict[str, Application]:
        result: dict[str, Application] = {}
        for row in self.connection.execute("SELECT job_id FROM applications"):
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
        return {r["job_id"] for r in self.connection.execute("SELECT job_id FROM applications")}

    # -- generated documents ------------------------------------------------

    def save_document(self, document: GeneratedDocument) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "INSERT INTO generated_documents(job_id, kind, payload) VALUES (?,?,?) "
                "ON CONFLICT(job_id, kind) DO UPDATE SET payload = excluded.payload",
                (document.job_id, document.kind, _json(document.model_dump(mode="json"))),
            )

    def get_document(self, job_id: str, kind: str) -> GeneratedDocument | None:
        row = self.connection.execute(
            "SELECT payload FROM generated_documents WHERE job_id = ? AND kind = ?",
            (job_id, kind),
        ).fetchone()
        return GeneratedDocument.model_validate(json.loads(row["payload"])) if row else None

    def documents_for(self, job_id: str) -> dict[str, GeneratedDocument]:
        rows = self.connection.execute(
            "SELECT kind, payload FROM generated_documents WHERE job_id = ?", (job_id,)
        )
        return {
            r["kind"]: GeneratedDocument.model_validate(json.loads(r["payload"])) for r in rows
        }

    # -- run log ------------------------------------------------------------

    def log_run(self, run: SearchRun) -> None:
        with self.transaction() as cursor:
            cursor.execute("INSERT INTO runs(payload) VALUES (?)", (_json(run.model_dump(mode="json")),))

    def recent_runs(self, limit: int = 20) -> list[SearchRun]:
        rows = self.connection.execute(
            "SELECT payload FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [SearchRun.model_validate(json.loads(r["payload"])) for r in rows]