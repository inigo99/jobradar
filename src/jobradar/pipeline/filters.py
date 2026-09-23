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
    """Is the job's location one of the user's areas? Whole words only."""
    return any(contains_phrase(job.location or "", area) for area in areas)


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
    """Work mode, with the local-area exception."""
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
        named = {code.upper() for code in (job.remote_regions or []) if len(code) == 2}
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
        regions = {region.upper() for region in (job.remote_regions or [])}
        if regions & eligible:
            return None
        # Continental shorthands the candidate's country may fall under.
        european = {"ES", "PT", "FR", "DE", "IT", "NL", "BE", "IE", "PL", "AT", "CH", "GB"}
        if eligible & european and regions & {"EMEA", "EU", "EUROPE"}:
            return None
        if not filters.allow_international_remote:
            return FilterOutcome(False, "international remote is switched off")
        return FilterOutcome(False, f"remote limited to {', '.join(job.remote_regions or [])}")

    # Scope unknown: keep it, but say so loudly.
    if not filters.allow_international_remote and job.country and job.country.upper() not in eligible:
        return FilterOutcome(False, "international remote is switched off")
    return FilterOutcome(True, warnings=("Remote scope not stated — confirm you may work from your country.",))


def _check_salary(job: Job, filters: Filters, rates: ExchangeRates | None) -> FilterOutcome | None:
    """Salary against the user's minimum — only a published figure can reject."""
    salary_obj = getattr(job, "salary", None)
    if not salary_obj:
        if filters.require_published_salary:
            return FilterOutcome(False, "no published salary")
        return FilterOutcome(True, warnings=("No salary information at all.",))

    published = salary_obj.origin == SalaryOrigin.PUBLISHED
    if filters.require_published_salary and not published:
        return FilterOutcome(False, "no published salary")
    if filters.min_salary is None:
        return None
        
    figure = salary_obj.maximum if published else getattr(salary_obj, "midpoint", None)
    if figure is None:
        figure = getattr(salary_obj, "midpoint", None)
    if figure is None:
        return FilterOutcome(True, warnings=("No salary information at all.",))
        
    amount: float = figure
    if salary_obj.currency != filters.salary_currency and rates is not None:
        converted = rates.convert(figure, salary_obj.currency, filters.salary_currency)
        if converted is None:
            return FilterOutcome(True, warnings=(f"Could not convert {salary_obj.currency}.",))
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
    """How many years the candidate can defend."""
    if filters.max_years_experience is not None:
        return float(filters.max_years_experience)
    if filters.use_profile_years and profile_years is not None:
        return float(profile_years)
    return None


def _check_experience(
    job: Job, filters: Filters, profile_years: float | None = None
) -> FilterOutcome | None:
    """Years asked for against years held — with a band for "just short"."""
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
    """Exclusion and required-keyword lists, matched as whole words."""
    haystack = f"{job.title or ''} {job.company or ''} {job.description or ''}"
    for company in filters.excluded_companies:
        if contains_phrase(job.company or "", company):
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
    tally: dict[str, int] = {}
    for reason in rejections.values():
        key = shape(reason)
        tally[key] = tally.get(key, 0) + 1
    return sorted(tally.items(), key=lambda item: -item[1])


def shape(reason: str) -> str:
    return re.sub(r"\d[\d,.]*", "N", (reason or "").split(" (")[0]).strip() or "unknown"


def category(reason: str) -> str:
    text = (reason or "").lower()
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