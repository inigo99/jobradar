"""The filter chain.

Every rule the user configured is applied here, in one place, and every
rejection carries a human-readable reason. That matters more than it sounds:
the usual failure mode of a job radar is a filter that is one notch too strict,
and without reasons the only symptom is an empty dashboard.

The chain is deliberately conservative about *missing* information. A job with
no stated salary is not dropped by the salary filter unless the user asked for
published salaries only; a remote job whose geographic restriction is unclear is
kept and flagged rather than discarded, because the alternative is silently
losing good jobs to bad metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..config import Filters
from ..models import Job, RemoteScope, SalaryOrigin, WorkMode
from ..textutils import contains_phrase
from .salary import ExchangeRates


@dataclass
class FilterOutcome:
    """Result of running the chain over one job."""

    keep: bool
    reason: str = ""
    #: Notes worth surfacing on a job that was kept anyway.
    warnings: tuple[str, ...] = ()


def _in_local_area(job: Job, areas: list[str]) -> bool:
    """Is the job's location one of the user's areas? Whole words only.

    Only the location is read: a company called "Madrid Tech" hiring in Berlin
    is not a Madrid job.
    """
    return any(contains_phrase(job.location, area) for area in areas)


def _check_freshness(job: Job, filters: Filters, today: date) -> FilterOutcome | None:
    age = job.age_days(today)
    if age is None:
        return None if filters.keep_undated else FilterOutcome(False, "no publication date")
    if age > filters.max_age_days:
        return FilterOutcome(False, f"published {age} days ago (limit {filters.max_age_days})")
    if age < 0:
        return FilterOutcome(False, "publication date is in the future")
    return None


def _check_work_mode(job: Job, filters: Filters) -> FilterOutcome | None:
    """Work mode, with the local-area exception.

    "Remote anywhere, but I would also take an office job in my own city" is
    the most common real-world preference, and it is expressed as a remote-only
    ``work_modes`` list plus a list of ``local_areas``.
    """
    if job.work_mode == WorkMode.UNKNOWN:
        return None  # unknown is resolved by enrichment, not by dropping the job
    if job.work_mode in filters.work_modes:
        return None
    if job.work_mode in (WorkMode.HYBRID, WorkMode.ONSITE) and _in_local_area(job, filters.local_areas):
        return None
    return FilterOutcome(False, f"work mode is {job.work_mode.value}")


def _check_geography(job: Job, filters: Filters) -> FilterOutcome | None:
    """Can the candidate actually hold this job from where they live?"""
    eligible = {c.upper() for c in filters.effective_countries()}

    # On-site and hybrid: the office has to be somewhere the candidate accepts.
    if job.work_mode in (WorkMode.ONSITE, WorkMode.HYBRID):
        if _in_local_area(job, filters.local_areas):
            return None
        if job.country and job.country.upper() in eligible:
            return None
        if not job.country and not filters.local_areas:
            return None
        return FilterOutcome(False, f"on-site/hybrid outside your areas ({job.location or 'unknown'})")

    # Remote: the question is what the ad's geographic restriction allows.
    if job.remote_scope == RemoteScope.WORLDWIDE:
        return None
    if job.remote_scope == RemoteScope.COUNTRY:
        # Countries the ad's own residency sentence names beat the listing's
        # metadata; with neither, the sentence is ambiguous ("must be eligible
        # to work in the country") and the job is kept and flagged rather
        # than dropped on a guess.
        named = {code.upper() for code in job.remote_regions if len(code) == 2}
        if named:
            if named & eligible:
                return None
            return FilterOutcome(False, f"remote but restricted to {', '.join(sorted(named))}")
        if job.country:
            if job.country.upper() in eligible:
                return None
            return FilterOutcome(False, f"remote but restricted to {job.country}")
        return FilterOutcome(
            True,
            warnings=("Remote with a residency condition that names no country — confirm it covers yours.",),
        )
    if job.remote_scope == RemoteScope.REGION:
        regions = {region.upper() for region in job.remote_regions}
        if regions & eligible:
            return None
        # Continental shorthands the candidate's country may fall under.
        european = {"ES", "PT", "FR", "DE", "IT", "NL", "BE", "IE", "PL", "AT", "CH", "GB"}
        if eligible & european and regions & {"EMEA", "EU", "EUROPE"}:
            return None
        if not filters.allow_international_remote:
            return FilterOutcome(False, "international remote is switched off")
        return FilterOutcome(False, f"remote limited to {', '.join(job.remote_regions)}")

    # Scope unknown: keep it, but say so loudly.
    if not filters.allow_international_remote and job.country and job.country.upper() not in eligible:
        return FilterOutcome(False, "international remote is switched off")
    return FilterOutcome(True, warnings=("Remote scope not stated — confirm you may work from your country.",))


def _check_salary(job: Job, filters: Filters, rates: ExchangeRates | None) -> FilterOutcome | None:
    """Salary against the user's minimum — only a published figure can reject.

    An estimate comes from a reference band, not from the ad; letting it drop
    a job means discarding a real opening on a guess. It is kept and flagged.
    A published band is compared by its top: a 36-45k band may well pay 40k,
    and rejecting it for its lower end punishes the ads that are transparent.
    """
    published = job.salary.origin == SalaryOrigin.PUBLISHED
    if filters.require_published_salary and not published:
        return FilterOutcome(False, "no published salary")
    if filters.min_salary is None:
        return None
    figure = job.salary.maximum if published else job.salary.midpoint
    if figure is None:
        figure = job.salary.midpoint
    if figure is None:
        return FilterOutcome(True, warnings=("No salary information at all.",))
    amount: float = figure
    if job.salary.currency != filters.salary_currency and rates is not None:
        converted = rates.convert(figure, job.salary.currency, filters.salary_currency)
        if converted is None:
            return FilterOutcome(True, warnings=(f"Could not convert {job.salary.currency}.",))
        amount = converted
    if amount >= filters.min_salary:
        return None
    if not published:
        return FilterOutcome(
            True,
            warnings=(
                f"Estimated salary ≈ {amount:,.0f} {filters.salary_currency}, below your minimum "
                "— an estimate, not the ad's figure.",
            ),
        )
    return FilterOutcome(
        False,
        f"salary ≈ {amount:,.0f} {filters.salary_currency} "
        f"(below {filters.min_salary:,} {filters.salary_currency})",
    )


def _experience_ceiling(filters: Filters, profile_years: float | None) -> float | None:
    """How many years the candidate can defend.

    An explicit ``max_years_experience`` wins, because a user who typed a
    number meant it. Otherwise the profile's own dates are used, which is the
    only version of this number that stays true without anyone maintaining it.
    """
    if filters.max_years_experience is not None:
        return float(filters.max_years_experience)
    if filters.use_profile_years and profile_years is not None:
        return float(profile_years)
    return None


def _check_experience(
    job: Job, filters: Filters, profile_years: float | None = None
) -> FilterOutcome | None:
    """Years asked for against years held — with a band for "just short".

    An ad that states no minimum is never dropped here. Most ads state none,
    and treating silence as a rejection would throw away the majority of the
    board to save the reader a sentence.
    """
    ceiling = _experience_ceiling(filters, profile_years)
    if ceiling is None or job.min_years_experience is None:
        return None
    short_by = job.min_years_experience - ceiling
    if short_by <= 0.001:
        return None
    held = f"{ceiling:g}"
    if short_by <= filters.years_margin + 0.001:
        return FilterOutcome(
            False,
            f"asks for {job.min_years_experience} years, you have {held} — "
            f"just short by {short_by:g}",
        )
    return FilterOutcome(
        False,
        f"asks for {job.min_years_experience} years, you have {held} "
        f"(short by {short_by:g})",
    )


def _check_keywords(job: Job, filters: Filters) -> FilterOutcome | None:
    """Exclusion and required-keyword lists, matched as whole words.

    Substring matching dropped "JavaScript Engineer" for an excluded "java" and
    "Talan" for an excluded "Alan". End an entry with ``*`` to match a prefix.
    """
    haystack = f"{job.title} {job.company} {job.description}"
    for company in filters.excluded_companies:
        if contains_phrase(job.company, company):
            return FilterOutcome(False, f"excluded company ({job.company})")
    for word in filters.excluded_keywords:
        if contains_phrase(haystack, word):
            return FilterOutcome(False, f"excluded keyword '{word}'")
    if filters.required_keywords:
        if not any(contains_phrase(haystack, word) for word in filters.required_keywords):
            return FilterOutcome(False, "none of the required keywords present")
    return None


def apply_filters(
    job: Job,
    filters: Filters,
    rates: ExchangeRates | None = None,
    today: date | None = None,
    profile_years: float | None = None,
) -> FilterOutcome:
    """Run every rule against ``job`` and return the first rejection, if any."""
    today = today or date.today()
    warnings: list[str] = []
    checks = (
        _check_freshness(job, filters, today),
        _check_work_mode(job, filters),
        _check_geography(job, filters),
        _check_salary(job, filters, rates),
        _check_experience(job, filters, profile_years),
        _check_keywords(job, filters),
    )
    for outcome in checks:
        if outcome is None:
            continue
        if not outcome.keep:
            return outcome
        warnings.extend(outcome.warnings)
    return FilterOutcome(True, warnings=tuple(warnings))


def explain(rejections: dict[str, str]) -> list[tuple[str, int]]:
    """Summarise why jobs were dropped, commonest reason first.

    Shown after every run so a filter that is quietly eating everything is
    immediately visible instead of looking like "there were no jobs today".
    """
    tally: dict[str, int] = {}
    for reason in rejections.values():
        key = shape(reason)
        tally[key] = tally.get(key, 0) + 1
    return sorted(tally.items(), key=lambda item: -item[1])


def shape(reason: str) -> str:
    """The reason with its specifics removed, for grouping.

    "published 9 days ago" and "published 12 days ago" are one problem, not
    two. Stored alongside every rejection so the tally survives the run that
    produced it.
    """
    return re.sub(r"\d[\d,.]*", "N", (reason or "").split(" (")[0]).strip() or "unknown"


def category(reason: str) -> str:
    """A coarse bucket for the dashboard's filter tally."""
    text = (reason or "").lower()
    # First: a duplicate's reason quotes the other job's title, which can
    # contain any of the words below.
    if text.startswith("duplicate"):
        return "duplicate"
    if "salary" in text:
        return "salary"
    if "years" in text:
        return "experience"
    if "work mode" in text:
        return "work mode"
    if "remote" in text or "on-site" in text or "outside your areas" in text:
        return "geography"
    if "keyword" in text or "excluded company" in text:
        return "keywords"
    if "published" in text or "publication date" in text:
        return "freshness"
    if "duplicate" in text:
        return "duplicate"
    return "other"
