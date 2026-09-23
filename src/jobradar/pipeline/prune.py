"""Retire old, untouched jobs without fetching them.

The sweep asks every source whether each ad is still open, which costs a
request per job — a real browser for the restricted sources — and only catches
ads that admit they are closed. Plenty never do: they sit on the board for
months after the shortlist is drawn.

This is the cheap half. Anything published more than ``prune_after_days`` ago
that the user has not touched is marked closed with the reason, so it leaves the
active board, stays readable, and — because closed jobs take part in
deduplication — does not come back as "new" when the ad is reposted under a new
id. A job with any tracking record (applied, discarded, a note) is never
pruned. Jobs with no publication date are left alone: their age is unknown.
"""

from __future__ import annotations

from datetime import date

from ..storage import Database


def prune_stale(database: Database, max_age_days: int | None, today: date | None = None) -> list[tuple[str, str]]:
    """Close untouched jobs older than ``max_age_days``. Returns ``(id, reason)``."""
    if not max_age_days or max_age_days <= 0:
        return []
    today = today or date.today()
    tracked = database.tracked_job_ids()
    pruned: list[tuple[str, str]] = []
    for job in database.list_jobs(include_closed=False):
        if job.id in tracked:
            continue
        age = job.age_days(today)
        if age is None or age <= max_age_days:
            continue
        reason = f"aged out: published {age} days ago and untouched (limit {max_age_days})"
        database.mark_closed(job.id, reason)
        pruned.append((job.id, reason))
    return pruned
