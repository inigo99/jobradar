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
from ..textutils import normalise
from .salary import ExchangeRates


@dataclass
class FilterOutcome:
    """Result of running the chain over one job."""

    keep: bool
    reason: str = ""
    #: Notes worth surfacing on a job that was kept anyway.
    warnings: tuple[str, ...] = ()


def _in_local_area(job: Job, areas: list[str]) -> bool:
    haystack = normalise(f"{job.location} {job.company}")
    return any(normalise(area) and normalise(area) in haystack for area in areas)


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
        if job.country and job.country.upper() in eligible:
            return None
        restrictions = ", ".join(job.remote_regions) or job.country or job.location
        return FilterOutcome(False, f"remote but restricted to {restrictions or 'another country'}")
    if job.remote_scope == RemoteScope.REGION:
        blob = normalise(" ".join(job.remote_regions))
        if any(normalise(code) in blob for code in eligible):
            return None
        # Continental shorthands the candidate's country may fall under.
        european = {"ES", "PT", "FR", "DE", "IT", "NL", "BE", "IE", "PL", "AT", "CH", "GB"}
        if eligible & european and any(tag in blob for tag in ("emea", "eu", "europe")):
            return None
        if not filters.allow_international_remote:
            return FilterOutcome(False, "international remote is switched off")
        return FilterOutcome(False, f"remote limited to {', '.join(job.remote_regions)}")

    # Scope unknown: keep it, but say so loudly.
    if not filters.allow_international_remote and job.country and job.country.upper() not in eligible:
        return FilterOutcome(False, "international remote is switched off")
    return FilterOutcome(True, warnings=("Remote scope not stated — confirm you may work from your country.",))


def _check_salary(job: Job, filters: Filters, rates: ExchangeRates | None) -> FilterOutcome | None:
    if filters.require_published_salary and job.salary.origin != SalaryOrigin.PUBLISHED:
        return FilterOutcome(False, "no published salary")
    if filters.min_salary is None:
        return None
    midpoint = job.salary.midpoint
    if midpoint is None:
        return FilterOutcome(True, warnings=("No salary information at all.",))
    amount = midpoint
    if job.salary.currency != filters.salary_currency and rates is not None:
        converted = rates.convert(midpoint, job.salary.currency, filters.salary_currency)
        if converted is None:
            return FilterOutcome(True, warnings=(f"Could not convert {job.salary.currency}.",))
        amount = converted
    if amount < filters.min_salary:
        return FilterOutcome(
            False,
            f"salary ≈ {amount:,.0f} {filters.salary_currency} "
            f"(below {filters.min_salary:,} {filters.salary_currency})",
        )
    return None


def _check_experience(job: Job, filters: Filters) -> FilterOutcome | None:
    if filters.max_years_experience is None or job.min_years_experience is None:
        return None
    if job.min_years_experience > filters.max_years_experience:
        return FilterOutcome(
            False, f"asks for {job.min_years_experience}+ years (limit {filters.max_years_experience})"
        )
    return None


def _check_keywords(job: Job, filters: Filters) -> FilterOutcome | None:
    haystack = normalise(f"{job.title} {job.company} {job.description}")
    for company in filters.excluded_companies:
        if normalise(company) and normalise(company) in normalise(job.company):
            return FilterOutcome(False, f"excluded company ({job.company})")
    for word in filters.excluded_keywords:
        if normalise(word) and normalise(word) in haystack:
            return FilterOutcome(False, f"excluded keyword '{word}'")
    if filters.required_keywords:
        if not any(normalise(word) in haystack for word in filters.required_keywords):
            return FilterOutcome(False, "none of the required keywords present")
    return None


def apply_filters(
    job: Job,
    filters: Filters,
    rates: ExchangeRates | None = None,
    today: date | None = None,
) -> FilterOutcome:
    """Run every rule against ``job`` and return the first rejection, if any."""
    today = today or date.today()
    warnings: list[str] = []
    checks = (
        _check_freshness(job, filters, today),
        _check_work_mode(job, filters),
        _check_geography(job, filters),
        _check_salary(job, filters, rates),
        _check_experience(job, filters),
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
        # Group by the shape of the reason, not its specifics: "published 9
        # days ago" and "published 12 days ago" are one problem, not two.
        key = re.sub(r"\d[\d,.]*", "N", reason.split(" (")[0]).strip()
        tally[key] = tally.get(key, 0) + 1
    return sorted(tally.items(), key=lambda item: -item[1])
