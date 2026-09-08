"""Deduplication.

The same opening routinely appears on three boards at once, plus once more via
a recruitment agency that hides the client's name. Left unchecked this is the
fastest way to make a job radar unusable, so duplicates are collapsed on three
increasingly forgiving signals:

1. the job id (same source, same ad);
2. an exact fingerprint of normalised company + title;
3. same company and a high token overlap in the title.

Only whole-token comparison is used. Substring matching looks tempting and is a
trap: "Alan" is inside "Talan", "UST" is inside "Braintrust", and the resulting
merges are silent and wrong.

When two records describe the same job, the more informative one wins — a
published salary and a longer description beat an empty stub — and the winner
inherits the other's apply URL if it had none.
"""

from __future__ import annotations

from ..models import Job, SalaryOrigin
from ..textutils import normalise, token_set

#: How much of the shorter title must overlap for two ads at the same company
#: to be considered the same job.
TITLE_OVERLAP = 0.72


def _informativeness(job: Job) -> tuple[int, int, int, int]:
    """Sort key: the higher, the better a record is worth keeping."""
    return (
        1 if job.salary.origin == SalaryOrigin.PUBLISHED else 0,
        1 if job.posted_at else 0,
        len(job.description or ""),
        len(job.requirements),
    )


def _same_job(left: Job, right: Job) -> bool:
    if not left.company or not right.company:
        return False
    if normalise(left.company) != normalise(right.company):
        return False
    left_tokens, right_tokens = token_set(left.title), token_set(right.title)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    return overlap >= TITLE_OVERLAP


def _merge(winner: Job, loser: Job) -> Job:
    """Fold anything the discarded record knew into the surviving one."""
    if not winner.apply_url and loser.link:
        winner.apply_url = loser.link
    if not winner.description and loser.description:
        winner.description = loser.description
    if winner.salary.origin != SalaryOrigin.PUBLISHED and loser.salary.origin == SalaryOrigin.PUBLISHED:
        winner.salary = loser.salary
    if not winner.posted_at and loser.posted_at:
        winner.posted_at = loser.posted_at
    if winner.min_years_experience is None:
        winner.min_years_experience = loser.min_years_experience
    for alert in loser.alerts:
        if alert not in winner.alerts:
            winner.alerts.append(alert)
    seen_also = winner.raw.setdefault("also_seen_on", [])
    if loser.source not in seen_also and loser.source != winner.source:
        seen_also.append(loser.source)
    return winner


def deduplicate(jobs: list[Job]) -> list[Job]:
    """Collapse duplicates, keeping the most informative record of each job."""
    ordered = sorted(jobs, key=_informativeness, reverse=True)

    by_id: dict[str, Job] = {}
    for job in ordered:
        job.ensure_id()
        existing = by_id.get(job.id)
        by_id[job.id] = _merge(existing, job) if existing else job

    by_fingerprint: dict[str, Job] = {}
    for job in by_id.values():
        key = job.fingerprint()
        existing = by_fingerprint.get(key)
        by_fingerprint[key] = _merge(existing, job) if existing else job

    survivors: list[Job] = []
    for job in by_fingerprint.values():
        for kept in survivors:
            if _same_job(kept, job):
                _merge(kept, job)
                break
        else:
            survivors.append(job)
    return survivors
