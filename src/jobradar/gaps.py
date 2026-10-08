"""What you lack most often: the gaps of the jobs on your board, added up.

Each job's score already lists the requirements your profile cannot meet. One
job's gap is something to answer honestly in its interview; the same gap in a
dozen jobs is something to learn. This adds them up across the board and puts
first what would pay most to close:

    priority = the sum, over the jobs that ask for it, of how hard each ad
               insists on it (its weight, 1–10) × how close you already are
               to that job (its tailored score; at least 10 %)

so a gap shared by jobs you nearly match outranks one that only far-off jobs
ask for. Each gap keeps the taxonomy's learning difficulty — *fast*, *medium*
or *slow* — which is what separates "read up on it this week" from "prepare an
honest answer instead". It never changes what your CV claims: a skill goes on
the CV when you have it, not when it would be useful.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .models import Application, ApplicationStatus, Job, MatchScore
from .taxonomy import difficulty_for, difficulty_note, label_for

#: A job you match poorly still counts, a little.
MIN_CLOSENESS = 0.10
#: Example jobs shown for each gap.
EXAMPLES = 3


@dataclass
class Gap:
    """One requirement your profile lacks, across every job asking for it."""

    key: str
    label: str
    difficulty: str
    note: str
    #: How many jobs on the board ask for it.
    jobs: int = 0
    #: The ads' average insistence on it, 1–10.
    weight: float = 0.0
    priority: float = 0.0
    #: "Company — Title" of the closest jobs asking for it, best first.
    examples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def skill_gaps(jobs: list[Job], applications: dict[str, Application],
               scores: dict[str, MatchScore], limit: int = 15) -> list[Gap]:
    """The gaps of the open jobs you have not discarded, most worth closing first."""
    gaps: dict[str, Gap] = {}
    weights: dict[str, float] = {}
    closest: dict[str, list[tuple[float, str]]] = {}
    for job in jobs:
        if job.closed:
            continue
        application = applications.get(job.id)
        if application is not None and application.status == ApplicationStatus.DISCARDED:
            continue
        score = scores.get(job.id)
        if score is None or not score.scored:
            continue
        closeness = max(MIN_CLOSENESS, score.tailored / 100)
        name = f"{job.company} — {job.title}" if job.company else job.title
        for detail in score.gap_details or []:
            key = str(detail.get("key") or "")
            if not key:
                continue
            weight = float(detail.get("weight") or 1)
            gap = gaps.get(key)
            if gap is None:
                gap = gaps[key] = Gap(
                    key=key,
                    label=str(detail.get("label") or label_for(key)),
                    difficulty=str(detail.get("difficulty") or difficulty_for(key)),
                    note=str(detail.get("note") or difficulty_note(key)),
                )
            gap.jobs += 1
            weights[key] = weights.get(key, 0.0) + weight
            gap.priority += weight * closeness
            closest.setdefault(key, []).append((score.tailored, name))
    for key, gap in gaps.items():
        gap.weight = round(weights[key] / gap.jobs, 1)
        gap.priority = round(gap.priority, 1)
        gap.examples = [name for _, name in sorted(closest[key], key=lambda item: -item[0])
                        ][:EXAMPLES]
    ranked = sorted(gaps.values(), key=lambda gap: (-gap.priority, -gap.jobs, gap.label))
    return ranked[:limit]
