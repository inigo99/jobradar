"""Match scoring — and the anti-fabrication lock that lives inside it.

A job is scored twice against the same profile:

*base*      what the CV proves as it stands today;
*tailored*  what it would prove if the relevant skills were pulled out of the
            "technical skills" list and into a bullet or the summary.

The gap between the two is the whole point of tailoring, and the rule that
makes the number honest is one line in :func:`promoted_prominence`: a skill the
candidate does not have has evidence 0.0, and 0.0 never rises. No amount of
tailoring can invent experience, so the tailored score can only ever reflect
*better presentation of things that are already true*.

Weights come from the job ad; evidence and ceilings come from the profile. See
``docs/CV_TAILORING.md`` for how to reason about your own ceilings.
"""

from __future__ import annotations

from ..models import Job, MatchScore, Profile, Requirement

#: Evidence at or above this counts as a genuine strength worth leading with.
STRONG = 0.7


def promoted_prominence(key: str, profile: Profile, surfaced: set[str]) -> float:
    """How strongly a tailored CV can present ``key``.

    The three rules, in order:

    1. Evidence 0.0 stays 0.0. The candidate does not have it; it is a gap, and
       the tailored CV must not claim it. This is the lock.
    2. A skill the tailored CV surfaces rises to its ceiling — how convincingly
       the candidate could defend it in an interview.
    3. Anything else keeps the evidence it already had.
    """
    base = profile.evidence.get(key, 0.0)
    if base <= 0.0:
        return 0.0
    if key in surfaced:
        return max(base, profile.ceiling.get(key, base))
    return base


def choose_surfaced(requirements: list[Requirement], profile: Profile, limit: int = 12) -> list[str]:
    """Pick which owned skills the tailored CV should promote.

    Only requirements the candidate can actually evidence are eligible, and
    they are ranked by how much promoting them would raise the score: a heavily
    weighted requirement the CV currently only mentions in passing is worth far
    more than one it already proves.
    """
    candidates: list[tuple[float, str]] = []
    for requirement in requirements:
        base = profile.evidence.get(requirement.key, 0.0)
        if base <= 0.0:
            continue
        ceiling = profile.ceiling.get(requirement.key, base)
        gain = max(0.0, ceiling - base) * requirement.weight
        candidates.append((gain, requirement.key))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    ordered: list[str] = []
    for _, key in candidates:
        if key not in ordered:
            ordered.append(key)
    return ordered[:limit]


def score_job(job: Job, profile: Profile) -> MatchScore:
    """Score ``job`` against ``profile``.

    Both scores are percentages of the total requirement weight, so they are
    comparable across jobs with different numbers of requirements. A job with
    no parsed requirements scores zero rather than raising — that state means
    "we could not read the ad", which the dashboard shows as such.
    """
    requirements = job.requirements
    total = sum(requirement.weight for requirement in requirements)
    if not total:
        return MatchScore()

    surfaced = choose_surfaced(requirements, profile)
    surfaced_set = set(surfaced)

    base_points = sum(
        requirement.weight * profile.evidence.get(requirement.key, 0.0)
        for requirement in requirements
    )
    tailored_points = sum(
        requirement.weight * promoted_prominence(requirement.key, profile, surfaced_set)
        for requirement in requirements
    )

    base = round(100 * base_points / total, 1)
    tailored = round(100 * tailored_points / total, 1)

    gaps = sorted(
        (r for r in requirements if profile.evidence.get(r.key, 0.0) <= 0.0),
        key=lambda r: -r.weight,
    )
    strengths = sorted(
        (r for r in requirements if profile.evidence.get(r.key, 0.0) >= STRONG),
        key=lambda r: -r.weight,
    )

    return MatchScore(
        base=base,
        tailored=tailored,
        delta=round(tailored - base, 1),
        improvement_pct=round(100 * (tailored - base) / base, 1) if base else 0.0,
        gaps=[r.label for r in gaps][:6],
        strengths=[r.label for r in strengths][:6],
        surfaced=surfaced,
    )
