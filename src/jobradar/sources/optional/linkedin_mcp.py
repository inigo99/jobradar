"""LinkedIn, signed in as you, through the LinkedIn MCP server. **Opt-in, restricted.**

Searches LinkedIn with your titles the way you would in your own browser —
which sees far more than the guest endpoint ``linkedin`` reads — and reads
each ad. The server and its client live in :mod:`jobradar.linkedin_mcp`.

LinkedIn returns ids, and only sometimes a title, so every ad is read during
the search: a title the search did show that matches none of yours is not
read, and no more than ``linkedin_mcp_reads`` ads are read per run. A reading
is kept on disk for a few days, so the next runs do not open the same ad.

Read ``tos_note`` before enabling this: it acts as your account.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from ...linkedin_mcp import (
    DEFAULT_COMMAND,
    HOMEPAGE,
    LinkedInMCP,
    LinkedInMCPError,
    Posting,
    job_ids,
    read_posting,
    titles_by_id,
)
from ...models import Job, WorkMode
from ...textutils import detect_language, title_matches
from ..base import Fetcher, JobSource, SearchQuery

log = logging.getLogger(__name__)

#: How many ads one run reads at most, unless Settings say otherwise.
DEFAULT_READS = 25
#: How long a reading is reused, in seconds.
READING_TTL = 3 * 86400


class LinkedInMCPSource(JobSource):
    id = "linkedin_mcp"
    name = "LinkedIn (your session, via MCP)"
    homepage = HOMEPAGE
    tos_tier = "restricted"
    tos_note = (
        "Reads LinkedIn signed in as you, through the LinkedIn MCP server: LinkedIn's User "
        "Agreement restricts automated access, and it can limit or close the account that "
        "does it. Enabling this source is your decision and your responsibility; keep the "
        "number of ads read per run low."
    )

    def __init__(self, fetcher: Fetcher, options: dict | None = None):
        super().__init__(fetcher, options)
        self.command = str(self.options.get("command") or DEFAULT_COMMAND)
        self.reads = int(self.options.get("reads") or DEFAULT_READS)
        #: A ready client, for tests; otherwise one is started on first use.
        self._client: Any = self.options.get("client")
        self._owns_client = self._client is None

    def client(self) -> Any:
        if self._client is None:
            self._client = LinkedInMCP(self.command)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    # -- search ------------------------------------------------------------

    def search(self, query: SearchQuery) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        budget = min(self.reads, query.limit)
        for term in query.terms():
            for location, work_type in self._places(query):
                result = self.client().call(
                    "search_jobs", keywords=term, location=location or None,
                    date_posted=_date_posted(query.max_age_days), work_type=work_type,
                    max_pages=1)
                titles = titles_by_id(result)
                for job_id in job_ids(result):
                    if job_id in seen:
                        continue
                    seen.add(job_id)
                    title = titles.get(job_id, "")
                    if title and query.titles and not title_matches(title, query.titles):
                        continue  # the search showed it: not one of yours, not worth a read
                    if self._cached(job_id) is None:  # a reading kept on disk costs nothing
                        if budget <= 0:
                            return jobs
                        budget -= 1
                    job = self.read(job_id, title)
                    if job is not None:
                        jobs.append(job)
        return jobs

    def _places(self, query: SearchQuery) -> list[tuple[str, str | None]]:
        """(location, work type) pairs to search, as the guest source does.

        Remote work is searched country by country with LinkedIn's remote
        filter; your areas without a filter, which is how hybrid and on-site
        jobs there show up.
        """
        from ...config import country_info

        places: list[tuple[str, str | None]] = []
        if query.remote_wanted or not query.local_areas:
            # Your areas cover on-site and hybrid; with none, the country does.
            remote = ("remote" if query.remote_wanted and (query.remote_only or query.local_areas)
                      else None)
            for code in query.countries or []:
                places.append((country_info(code).get("name", code), remote))
            if not places:
                places.append(("", remote))
        for area in query.local_areas:
            places.append((area, None))
        return places

    # -- reading one ad ----------------------------------------------------

    def read(self, job_id: str, title: str = "") -> Job | None:
        """The ad ``job_id`` as a job, or None when it is closed or unreadable."""
        posting = self.posting(job_id, title)
        if posting is None or posting.state == "closed" or not posting.title:
            return None
        return self.job_from(posting)

    def posting(self, job_id: str, title: str = "", fresh: bool = False) -> Posting | None:
        """The posting, from the disk if it was read lately."""
        cached = None if fresh else self._cached(job_id)
        if cached is not None:
            return cached
        try:
            result = self.client().call("get_job_details", job_id=job_id)
        except LinkedInMCPError as exc:
            if _is_setup(exc):
                raise
            log.info("Could not read LinkedIn ad %s: %s", job_id, exc)
            return None
        posting = read_posting(job_id, result, title)
        self._store(posting)
        return posting

    def job_from(self, posting: Posting) -> Job:
        job = self.make_job(
            posting.job_id,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            work_mode=posting.work_mode,
            url=posting.url,
            posted_at=posting.posted_at,
            description=posting.description,
        )
        if posting.description:
            job.language = detect_language(posting.description)
        if posting.work_mode != WorkMode.UNKNOWN:
            job.raw["linkedin_badge"] = posting.work_mode.value
        if posting.state == "applied":
            job.raw["applied_on_linkedin"] = True
        return job

    def resolve_work_mode(self, job: Job) -> WorkMode | None:
        badge = job.raw.get("linkedin_badge")
        return WorkMode(badge) if badge else None

    def check_open(self, job: Job) -> tuple[bool, str]:
        posting = self.posting(job.native_id, job.title, fresh=True)
        if posting is not None and posting.state == "closed":
            return False, "No longer accepting applications"
        return True, ""

    # -- the readings kept on disk -------------------------------------------

    def _path(self, job_id: str) -> Path | None:
        cache_dir = getattr(self.fetcher, "cache_dir", None)
        return Path(cache_dir) / "linkedin-mcp" / f"{job_id}.json" if cache_dir else None

    def _cached(self, job_id: str) -> Posting | None:
        path = self._path(job_id)
        if path is None or not path.exists() or time.time() - path.stat().st_mtime > READING_TTL:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["work_mode"] = WorkMode(data.get("work_mode") or "unknown")
            data["posted_at"] = date.fromisoformat(data["posted_at"]) if data.get("posted_at") \
                else None
            return Posting(**data)
        except (OSError, ValueError, TypeError):
            return None

    def _store(self, posting: Posting) -> None:
        path = self._path(posting.job_id)
        if path is None:
            return
        data = asdict(posting)
        data["work_mode"] = posting.work_mode.value
        data["posted_at"] = posting.posted_at.isoformat() if posting.posted_at else None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.debug("Could not keep the LinkedIn reading of %s: %s", posting.job_id, exc)


def _is_setup(exc: LinkedInMCPError) -> bool:
    """Whether a failure is about the server or the session, not one ad."""
    return bool(exc.hint) or "did not start" in exc.message or "is closed" in exc.message


def _date_posted(days: int) -> str:
    """LinkedIn's recency filter for ads up to ``days`` old."""
    if days <= 1:
        return "past_24_hours"
    if days <= 7:
        return "past_week"
    return "past_month"
