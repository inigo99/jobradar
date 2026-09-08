"""The closed-advertisement sweep.

Run this before searching for anything new. A dashboard whose "active" tab is
half dead links stops being trusted within about a week, and re-checking is far
cheaper than re-reading.

The rule that keeps the data honest: **a job the user has touched is never
withdrawn.** If they applied, were rejected, discarded it or left a note, the
record stays — closing an ad they applied to would orphan their own history.
Only untouched, still-active jobs are swept, and even then they are marked
closed rather than deleted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..models import ApplicationStatus, Job
from ..sources import build_sources
from ..sources.base import JobSource
from ..storage import Database

log = logging.getLogger(__name__)


@dataclass
class SweepReport:
    checked: int = 0
    closed: list[tuple[str, str, str]] = field(default_factory=list)  # (id, title, reason)
    skipped_tracked: int = 0
    unreachable: int = 0

    def summary(self) -> str:
        return (
            f"checked {self.checked}, closed {len(self.closed)}, "
            f"kept {self.skipped_tracked} tracked, {self.unreachable} unreachable"
        )


def sweep_closed(database: Database, limit: int | None = None) -> SweepReport:
    """Check every untouched active job and mark the dead ones closed."""
    settings = database.load_settings()
    sources, fetcher = build_sources(settings, database.paths.cache_dir)
    by_id: dict[str, JobSource] = {source.id: source for source in sources}
    tracked = {
        job_id
        for job_id, application in database.all_applications().items()
        if application.status != ApplicationStatus.ACTIVE or application.notes
    }

    report = SweepReport()
    try:
        for job in database.list_jobs(include_closed=False):
            if limit is not None and report.checked >= limit:
                break
            if job.id in tracked:
                report.skipped_tracked += 1
                continue
            source = by_id.get(job.source)
            if source is None:
                continue  # source disabled since the job was collected
            report.checked += 1
            try:
                is_open, reason = source.check_open(job)
            except Exception as exc:
                log.debug("Could not check %s: %s", job.id, exc)
                report.unreachable += 1
                continue
            if not is_open:
                database.mark_closed(job.id, reason or "closed")
                report.closed.append((job.id, f"{job.company} — {job.title}", reason))
    finally:
        fetcher.close()
    return report


def reopen(database: Database, job: Job) -> None:
    """Undo a sweep decision, e.g. after fixing a moved apply URL."""
    with database.transaction() as cursor:
        cursor.execute("UPDATE jobs SET closed = 0, closed_reason = '' WHERE id = ?", (job.id,))
        cursor.execute("DELETE FROM closed_jobs WHERE job_id = ?", (job.id,))
