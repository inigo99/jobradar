"""Manfred — public JSON API of a Spanish tech-recruiting board.

Endpoints (no key, no browser):

* listing: ``https://www.getmanfred.com/api/v2/public/offers?lang=ES&onlyActive=true``
* one ad:  ``https://www.getmanfred.com/api/v2/public/offers/<id>?lang=ES``

Manfred is small but unusually well structured, which makes it worth more than
its volume suggests:

* every ad publishes a salary band (Manfred requires it);
* ``remotePercentage`` states the work mode as a number — 100 remote, 0
  on-site, anything between hybrid — instead of leaving it to a sentence;
* the ad page lists the required techniques with a *section* (``MUST`` /
  ``COULD`` / ``EXTRA``) and a *level* (``BASIC`` / ``INTERMEDIATE`` /
  ``ADVANCED``), which become weighted requirements directly instead of being
  guessed from the text.

Two shapes of the real API differ from what one would expect, and both are
handled: ``locations`` is a list of plain strings (``["Vigo, España"]``), not
of objects, and ``responsibilities`` is a list of Markdown strings, not one
HTML block. Manfred only exposes ``updatedAt``, not a publication date; for an
ad not seen before the two are the same thing.
"""

from __future__ import annotations

from typing import Any

from ..models import Job, Requirement, Salary, SalaryOrigin, WorkMode
from ..taxonomy import label_for, skill_for_name
from ..textutils import parse_date, strip_html
from .base import JobSource, SearchQuery

LISTING = "https://www.getmanfred.com/api/v2/public/offers"
DETAIL = "https://www.getmanfred.com/api/v2/public/offers/{offer_id}"
PARAMS = {"lang": "ES", "currency": "€"}

#: Requirement weight by (section, level): a MUST at ADVANCED is what the job
#: *is*; an EXTRA at BASIC is a passing mention. Same 1-10 scale as the rest.
WEIGHTS: dict[str, dict[str, int]] = {
    "MUST": {"ADVANCED": 10, "INTERMEDIATE": 8, "BASIC": 7},
    "COULD": {"ADVANCED": 6, "INTERMEDIATE": 5, "BASIC": 4},
    "EXTRA": {"ADVANCED": 4, "INTERMEDIATE": 3, "BASIC": 2},
}
DEFAULT_WEIGHT = 5


def work_mode_from(percentage: Any) -> WorkMode:
    """``remotePercentage`` -> work mode. Missing means unknown, not on-site."""
    try:
        value = float(percentage)
    except (TypeError, ValueError):
        return WorkMode.UNKNOWN
    if value >= 100:
        return WorkMode.REMOTE
    if value > 0:
        return WorkMode.HYBRID
    return WorkMode.ONSITE


def _place(location: Any) -> str:
    """A location entry as text: a string in the live API, a dict in older data."""
    if isinstance(location, str):
        return location
    if isinstance(location, dict):
        return str(location.get("city") or location.get("town") or "")
    return ""


def _text(value: Any) -> str:
    """Plain text from an HTML string or a list of Markdown strings."""
    if isinstance(value, list):
        value = "\n".join(str(item) for item in value)
    return strip_html(str(value or ""))


def requirements_from(techs: list[dict]) -> list[Requirement]:
    """Weighted requirements from the ad's technique list.

    A technique the skill taxonomy does not recognise is kept under its own
    name: it still shows as a requirement, and counts as a gap until the
    profile has evidence for it, which is the honest reading.
    """
    requirements: dict[str, Requirement] = {}
    for tech in techs or []:
        if not isinstance(tech, dict):
            continue
        name = str(tech.get("name") or "").strip()
        if not name:
            continue
        weight = WEIGHTS.get(str(tech.get("section")), {}).get(str(tech.get("level")),
                                                              DEFAULT_WEIGHT)
        known = skill_for_name(name)
        key = known or name.lower()
        label = label_for(known) if known else name
        current = requirements.get(key)
        if current is None or current.weight < weight:
            requirements[key] = Requirement(key=key, label=label, weight=weight)
    return sorted(requirements.values(), key=lambda r: -r.weight)


class ManfredSource(JobSource):
    id = "manfred"
    name = "Manfred"
    homepage = "https://www.getmanfred.com"
    tos_tier = "open"
    supports_remote_filter = True

    def search(self, query: SearchQuery) -> list[Job]:
        payload = self.fetcher.get_json(LISTING, params={**PARAMS, "onlyActive": "true"})
        entries = payload if isinstance(payload, list) else (payload or {}).get("offers") or []
        terms = [t.lower() for t in query.terms()]
        jobs: list[Job] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("position") or "")
            if terms and not any(term in title.lower() for term in terms):
                continue  # the listing has no description; the title decides
            job = self._parse(entry)
            if job is not None:
                jobs.append(job)
            if len(jobs) >= query.limit:
                break
        return jobs

    def _parse(self, entry: dict) -> Job | None:
        offer_id = entry.get("id")
        slug = str(entry.get("slug") or "")
        if offer_id is None and not slug:
            return None
        salary = Salary()
        try:
            figures = [float(v) for v in (entry.get("salaryFrom"), entry.get("salaryTo")) if v]
        except (TypeError, ValueError):
            figures = []
        if figures:
            try:
                salary = Salary(
                    minimum=int(min(figures)),
                    maximum=int(max(figures)),
                    currency="EUR",
                    origin=SalaryOrigin.PUBLISHED,
                    basis="Published on Manfred (every Manfred ad publishes a band).",
                )
            except (TypeError, ValueError):
                salary = Salary()
        places = [p for p in (_place(loc) for loc in entry.get("locations") or []) if p]
        company = entry.get("company") or {}
        return self.make_job(
            str(offer_id if offer_id is not None else slug),
            title=str(entry.get("position") or ""),
            company=str(company.get("name") if isinstance(company, dict) else company or ""),
            location=" / ".join(places) or "Remote",
            country="ES",
            work_mode=work_mode_from(entry.get("remotePercentage")),
            url=f"https://www.getmanfred.com/ofertas-empleo/{offer_id}/{slug}".rstrip("/"),
            posted_at=parse_date(entry.get("updatedAt")),
            language="es",
            salary=salary,
            raw={"slug": slug, "remote_percentage": entry.get("remotePercentage")},
        )

    def fetch_description(self, job: Job) -> str:
        """The ad text, plus the structured techniques as requirements."""
        detail = self.fetcher.get_json(DETAIL.format(offer_id=job.native_id), params=PARAMS)
        if not isinstance(detail, dict):
            return job.description or ""
        requirements = requirements_from(detail.get("techs") or [])
        if requirements:
            job.requirements = requirements
            # Enrichment must not replace these with a guess from the text.
            job.raw["structured_requirements"] = True
        languages = [f"{item.get('name')} ({item.get('level')})"
                     for item in detail.get("languages") or [] if isinstance(item, dict)]
        if languages:
            job.raw["languages"] = languages
        parts = [
            _text(detail.get("whatTheyAskFor")),
            _text(detail.get("responsibilities") or detail.get("whatWillYouDo")),
            _text(detail.get("description")),
        ]
        return "\n\n".join(part for part in parts if part) or job.description or ""
