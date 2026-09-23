"""Turning a raw listing into a job JobRadar can reason about.

Board listings are thin: a title, a company, a link and — if you are lucky — a
work-mode tag that is right about two thirds of the time. Enrichment fetches the
full advertisement and derives the fields the filters and the scorer need.

Every field has a deterministic path and, when a language model is configured,
a better one. The deterministic path is not a stub: it reads work mode,
geographic restriction, minimum experience, published salary and a weighted
requirement list out of the text with the taxonomy. The model earns its keep on
the ambiguous cases — an ad that mentions "remote" three times and then buries
"two days on site" in the last paragraph.
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..llm import LLMClient
from ..llm.prompts import read_job_ad
from ..models import Job, RemoteScope, Requirement, Salary, SalaryOrigin, WorkMode
from ..taxonomy import find_skills, label_for
from ..textutils import (
    detect_language,
    detect_remote_scope,
    detect_work_mode,
    extract_min_years,
    extract_salary,
    remote_scope_evidence,
    work_mode_evidence,
)
from .salary import ExchangeRates, normalise_salary

log = logging.getLogger(__name__)

#: Sections whose contents the ad genuinely insists on.
REQUIREMENT_MARKERS = (
    "requirements", "requisitos", "what you'll need", "what we're looking for",
    "qué buscamos", "que buscamos", "must have", "imprescindible", "essential",
    "qualifications", "perfil", "anforderungen", "profil",
)
NICE_TO_HAVE_MARKERS = (
    "nice to have", "bonus", "plus", "valorable", "se valorará", "deseable",
    "preferred", "would be great",
)

MAX_REQUIREMENTS = 20

#: Phrases that mean the real employer is hidden behind an intermediary.
AGENCY_MARKERS = (
    "our client", "nuestro cliente", "cliente final", "on behalf of our client",
    "leading company in the sector", "importante empresa del sector",
    "empresa líder del sector", "confidential client",
)


# ---------------------------------------------------------------------------
# Requirement extraction without a model
# ---------------------------------------------------------------------------


def _section_weight(description: str, alias_position: int) -> int:
    """Weight bonus based on which part of the ad a skill appeared in."""
    before = description[:alias_position].lower()
    last_required = max((before.rfind(marker) for marker in REQUIREMENT_MARKERS), default=-1)
    last_optional = max((before.rfind(marker) for marker in NICE_TO_HAVE_MARKERS), default=-1)
    if last_optional > last_required:
        return -2
    if last_required >= 0:
        return 2
    return 0


def extract_requirements_by_keyword(job: Job) -> list[Requirement]:
    """Weighted requirements derived from the taxonomy alone.

    Weighting is crude but defensible: something named in the title is what the
    job is; something repeated is insisted on; something inside a "nice to have"
    section is not. Crude and transparent beats clever and unexplainable — the
    user can see exactly why a requirement scored what it did.
    """
    title_hits = find_skills(job.title)
    body_hits = find_skills(job.description or "")
    lowered = (job.description or "").lower()

    requirements: list[Requirement] = []
    for key in set(title_hits) | set(body_hits):
        count = body_hits.get(key, 0)
        if key in title_hits:
            weight = 10
        elif count >= 4:
            weight = 8
        elif count >= 2:
            weight = 6
        else:
            weight = 4
        position = lowered.find(label_for(key).lower())
        if position >= 0:
            weight += _section_weight(lowered, position)
        requirements.append(Requirement(key=key, label=label_for(key), weight=weight))

    requirements.sort(key=lambda requirement: -requirement.weight)
    return requirements[:MAX_REQUIREMENTS]


# ---------------------------------------------------------------------------
# Deterministic field derivation
# ---------------------------------------------------------------------------


def derive_fields(job: Job) -> Job:
    """Fill in whatever can be read from the ad text without a model."""
    text = job.description or ""
    if text:
        job.language = detect_language(text, job.language)
        detected_mode = detect_work_mode(text, job.location)
        # The ad's own words beat the board's tag; boards mislabel hybrid roles
        # as remote constantly. But silence is not a contradiction: when the
        # text says nothing, a remote tag stays and is flagged, instead of the
        # job being demoted to "unknown" or dropped.
        if detected_mode != WorkMode.UNKNOWN:
            job.work_mode = detected_mode
            job.raw.pop("remote_unconfirmed", None)
        elif job.work_mode == WorkMode.REMOTE:
            job.raw["remote_unconfirmed"] = True
        evidence = work_mode_evidence(text)
        if evidence:
            job.raw["work_mode_evidence"] = evidence
        if job.remote_scope == RemoteScope.UNKNOWN:
            job.remote_scope, job.remote_regions = detect_remote_scope(text)
        scope_sentence = remote_scope_evidence(text)
        if scope_sentence:
            job.raw["remote_scope_evidence"] = scope_sentence
        if job.min_years_experience is None:
            job.min_years_experience = extract_min_years(text)
        if job.salary.origin != SalaryOrigin.PUBLISHED:
            published = extract_salary(text, job.salary.currency or "EUR")
            if published:
                job.salary = published
    return job


def derive_alerts(job: Job) -> list[str]:
    """Things the user must clarify before spending an hour on an application."""
    alerts: list[str] = []
    lowered = f"{job.company} {job.description}".lower()

    if job.raw.get("remote_unconfirmed"):
        alerts.append(
            "Listed as remote by the board, but the ad text never says so — confirm the work mode."
        )
    if (
        job.remote_scope == RemoteScope.COUNTRY
        and not job.remote_regions
        and job.raw.get("remote_scope_evidence")
    ):
        alerts.append(
            "Residency condition that names no country: "
            f"\u201c{job.raw['remote_scope_evidence']}\u201d — confirm it covers yours."
        )
    if job.work_mode == WorkMode.REMOTE and job.remote_scope == RemoteScope.UNKNOWN:
        alerts.append("Remote, but the ad does not say from which countries — confirm before applying.")
    if any(marker in lowered for marker in AGENCY_MARKERS):
        alerts.append("The end client is not named — ask who the employer actually is.")
    if job.salary.origin == SalaryOrigin.ESTIMATED:
        alerts.append("Salary is an estimate, not a published figure.")
    if job.work_mode == WorkMode.UNKNOWN:
        alerts.append("Work mode unclear — check whether office days are expected.")
    if job.posted_at is None:
        alerts.append("No publication date; the ad may be older than it looks.")
    return alerts


# ---------------------------------------------------------------------------
# The model-assisted path
# ---------------------------------------------------------------------------


def _apply_model_reading(job: Job, data: dict) -> None:
    """Merge the model's reading of an ad into the job, defensively.

    Anything malformed is ignored rather than trusted: a model that returns a
    salary of "competitive" must not be able to blank a published figure.
    """
    requirements: list[Requirement] = []
    for entry in data.get("requirements") or []:
        try:
            requirements.append(
                Requirement(
                    key=str(entry["key"]).strip().lower().replace(" ", "_"),
                    label=str(entry.get("label") or entry["key"]),
                    weight=int(entry.get("weight", 5)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if requirements:
        job.requirements = requirements[:MAX_REQUIREMENTS]

    try:
        job.work_mode = WorkMode(data.get("work_mode", job.work_mode))
    except ValueError:
        pass
    try:
        job.remote_scope = RemoteScope(data.get("remote_scope", job.remote_scope))
    except ValueError:
        pass
    regions = data.get("remote_regions")
    if isinstance(regions, list) and regions:
        job.remote_regions = [str(region) for region in regions]

    years = data.get("min_years_experience")
    if isinstance(years, int) and 0 < years <= 25:
        job.min_years_experience = years

    salary = data.get("salary") or {}
    if salary.get("published") and salary.get("minimum"):
        try:
            job.salary = Salary(
                minimum=int(salary["minimum"]),
                maximum=int(salary.get("maximum") or salary["minimum"]),
                currency=str(salary.get("currency") or "EUR").upper(),
                origin=SalaryOrigin.PUBLISHED,
                basis="Published in the job ad (read by the language model).",
            )
        except (TypeError, ValueError):
            pass

    language = data.get("language")
    if isinstance(language, str) and len(language) == 2:
        job.language = language

    for alert in data.get("alerts") or []:
        text = str(alert).strip()
        if text and text not in job.alerts:
            job.alerts.append(text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def enrich_job(
    job: Job,
    settings: Settings,
    llm: LLMClient | None = None,
    rates: ExchangeRates | None = None,
    fetch_description=None,
) -> Job:
    """Bring one job up to the standard the rest of the pipeline expects.

    ``fetch_description`` is the owning source's method, passed in rather than
    looked up so this function stays testable without any network.
    """
    if fetch_description and len(job.description or "") < 400:
        try:
            job.description = fetch_description(job) or job.description
        except Exception as exc:  # a source must never break a whole run
            log.debug("Could not fetch the full ad for %s: %s", job.id, exc)

    derive_fields(job)

    used_model = False
    if llm and settings.llm.enrich_jobs and (job.description or ""):
        system, user = read_job_ad(job)
        data = llm.complete_json(system, user)
        if isinstance(data, dict):
            _apply_model_reading(job, data)
            used_model = True

    if not job.requirements:
        job.requirements = extract_requirements_by_keyword(job)

    job.salary = normalise_salary(job, settings.filters.salary_currency, rates)

    for alert in derive_alerts(job):
        if alert not in job.alerts:
            job.alerts.append(alert)

    job.raw["enriched_by"] = "llm" if used_model else "rules"
    return job
