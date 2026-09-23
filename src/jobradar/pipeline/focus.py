"""Focus: which of today's jobs is worth an application *now*.

Match score answers "could I do this job". It does not answer "is it worth
applying today", and once a profile covers most of what the ads ask for, the
first question stops discriminating: everything clusters near the top and
sorting by match is sorting by noise.

Focus does not try to predict who will reply — nobody has the sample size for
that. It only demotes what is already known to go nowhere, which is a different
and much better-evidenced claim:

**Old ads.** An ad from three weeks ago has usually closed, or the shortlist is
already drawn. The sweep only retires ads that say so; plenty of dead ones
never do.

**Senior titles.** "Senior", "Lead", "Principal", "Head of" — when the ad's
title is aiming above the candidate's years, the filter that ends the
application is seniority, not the tech stack.

**Unpublished salary.** Not a reason to drop anything, but between two similar
ads the one that publishes a band saves an entire round.

Each factor is a multiplier on the match score, and every job carries a
sentence saying why it sits where it does. A ranking nobody can audit is a
ranking nobody should trust, and one line of explanation is the difference.

Nothing here is stored: focus is computed at display time so it cannot go
stale, and ``score.tailored`` is untouched so the honest match number is always
one click away.
"""

from __future__ import annotations

import re
from datetime import date

from ..models import Job, MatchScore

#: Title words that, in practice, mean the shortlist wants more years than a
#: mid-level candidate has. Matched as whole words in several languages,
#: because a job board does not translate its titles for you.
SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|head\s+of|chief|director|manager|"
    r"architect|arquitect[oa]|expert|experte|erfahren|responsable)\b",
    re.IGNORECASE,
)

#: (age in days, multiplier, reason). The first bracket an ad falls into wins.
FRESHNESS = (
    (7, 1.00, ""),
    (14, 0.85, "posted over a week ago"),
    (21, 0.55, "posted over two weeks ago"),
    (10**6, 0.25, "posted over three weeks ago — probably closed"),
)

SENIOR_PENALTY = 0.55
PUBLISHED_SALARY_BONUS = 1.06


def _freshness(age_days: int | None) -> tuple[float, str]:
    if age_days is None:
        return 1.0, ""          # no date is not evidence of staleness
    for limit, factor, reason in FRESHNESS:
        if age_days <= limit:
            return factor, reason
    return FRESHNESS[-1][1], FRESHNESS[-1][2]


def is_senior_title(title: str | None) -> bool:
    return bool(SENIOR_TITLE.search(title or ""))


def focus_for(
    job: Job,
    score: MatchScore | None,
    today: date | None = None,
    max_years: float | None = None,
) -> tuple[float, str]:
    """``(focus, reason)`` for one job.

    ``max_years`` is the candidate's own years of experience. When given, a
    senior title is only penalised if the ad also asks for more years than the
    candidate has, or says nothing about years — an ad titled "Senior Engineer"
    that then asks for three years is not actually out of reach.
    """
    base = score.tailored if score else 0.0
    factor, freshness_reason = _freshness(job.age_days(today))
    reasons = [freshness_reason] if freshness_reason else []

    if is_senior_title(job.title):
        asks = job.min_years_experience
        out_of_reach = max_years is None or asks is None or asks > max_years
        if out_of_reach:
            factor *= SENIOR_PENALTY
            reasons.append("the title is pitched at a senior or architect profile")

    salary_origin = getattr(job.salary, "origin", None)
    if getattr(salary_origin, "value", None) == "published":
        factor *= PUBLISHED_SALARY_BONUS
        reasons.append("publishes a salary band")

    return round(base * factor, 1), "; ".join(reasons)


def rank(
    jobs: list[tuple[Job, MatchScore | None]],
    today: date | None = None,
    max_years: float | None = None,
) -> list[tuple[Job, MatchScore | None, float, str]]:
    """Every job with its focus, highest first."""
    scored = [
        (job, score) + focus_for(job, score, today, max_years)
        for job, score in jobs
    ]
    scored.sort(key=lambda item: -item[2])
    return scored
