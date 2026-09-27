"""EURES — the European Commission's job mobility portal.

Around three million vacancies from the public employment services of the EU,
Norway, Iceland, Liechtenstein and Switzerland: nursing, teaching, trades,
care, hospitality, offices — every sector, since most of them come straight
from each country's own public job board (Spain's regional services
included).

The search is the JSON API the portal's own page calls, with no key;
https://github.com/rorar/eures-api-documentation documents it. One POST per
search term, restricted to your countries and to the age limit in your
filters; the ad text comes in the same answer, so nothing else is fetched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..config import country_info
from ..models import Job, Salary
from ..textutils import detect_remote_scope, detect_work_mode, extract_salary, strip_html
from .base import JobSource, SearchQuery

SEARCH = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
AD_PAGE = "https://europa.eu/eures/portal/jv-se/jv-details/{id}?jvDisplayLanguage={lang}"
PAGE_SIZE = 50
#: Countries EURES covers (ISO 3166-1 alpha-2).
COVERED = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IS",
    "IE", "IT", "LV", "LI", "LT", "LU", "MT", "NL", "NO", "PL", "PT", "RO", "SK", "SI",
    "ES", "SE", "CH",
})
#: EURES uses NUTS codes, which differ from ISO for one country.
NUTS = {"GR": "el"}
#: The languages the portal can answer in.
LANGUAGES = frozenset({
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "ga", "hr", "hu", "is",
    "it", "lt", "lv", "mt", "nl", "no", "pl", "pt", "ro", "sk", "sl", "sv",
})


def publication_period(max_age_days: int) -> str | None:
    """The portal's age filter closest to (and not narrower than) ours."""
    for days, period in ((1, "LAST_DAY"), (3, "LAST_THREE_DAYS"), (7, "LAST_WEEK"),
                         (31, "LAST_MONTH")):
        if max_age_days <= days:
            return period
    return None


class EuresSource(JobSource):
    id = "eures"
    name = "EURES (EU public employment services)"
    homepage = "https://europa.eu/eures/portal/jv-se/home"
    tos_tier = "open"
    tos_note = ("Public JSON API behind the European Commission's job search, no key; "
                "documented by the community, not by the Commission.")

    def search(self, query: SearchQuery) -> list[Job]:
        countries = [c.upper() for c in query.countries]
        covered = [c for c in countries if c in COVERED]
        if countries and not covered:
            return []  # none of your countries is in EURES
        locations = [NUTS.get(c, c.lower()) for c in covered]
        language = next((lang for lang in query.languages if lang in LANGUAGES), "en")
        session = f"jobradar-{uuid.uuid4().hex[:12]}"
        jobs: list[Job] = []
        seen: set[str] = set()
        for term in query.terms():
            payload = {
                "resultsPerPage": PAGE_SIZE,
                "page": 1,
                "sortSearch": "BEST_MATCH",
                "keywords": [{"keyword": term, "specificSearchCode": "EVERYWHERE"}],
                "publicationPeriod": publication_period(query.max_age_days),
                "occupationUris": [], "skillUris": [], "requiredExperienceCodes": [],
                "positionScheduleCodes": [], "sectorCodes": [],
                "educationAndQualificationLevelCodes": [], "positionOfferingCodes": [],
                "locationCodes": locations, "euresFlagCodes": [], "otherBenefitsCodes": [],
                "requiredLanguages": [], "minNumberPost": None,
                "sessionId": session, "requestLanguage": language,
            }
            answer = self.fetcher.post_json(SEARCH, payload)
            for entry in (answer or {}).get("jvs") or []:
                job = self._parse(entry, language)
                if job is None or job.native_id in seen:
                    continue
                seen.add(job.native_id)
                jobs.append(job)
                if len(jobs) >= query.limit:
                    return jobs
        return jobs

    def _parse(self, entry: dict, request_language: str) -> Job | None:
        vacancy_id = str(entry.get("id") or "")
        if not vacancy_id:
            return None
        # The ad as its employer wrote it, not the portal's machine translation.
        languages = entry.get("availableLanguages") or []
        original = languages[0] if languages else request_language
        text = (entry.get("translations") or {}).get(original) or {}
        title = str(text.get("title") or entry.get("title") or "")
        description = strip_html(str(text.get("description") or entry.get("description") or ""))
        places = entry.get("locationMap") or {}
        country = next(iter(places), "")
        location = country_info(country).get("name", country) if country else ""
        created = entry.get("creationDate")
        posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).date()
                  if isinstance(created, (int, float)) else None)
        scope, regions = detect_remote_scope(description)
        work_mode = detect_work_mode(description, location)
        currency = country_info(country).get("currency", "EUR") if country else "EUR"
        return self.make_job(
            vacancy_id,
            title=title,
            company=str((entry.get("employer") or {}).get("name") or ""),
            location=location,
            country=country,
            work_mode=work_mode,
            remote_scope=scope,
            remote_regions=regions,
            url=AD_PAGE.format(id=vacancy_id, lang=original),
            posted_at=posted,
            description=description,
            language=original,
            salary=extract_salary(description, currency) or Salary(),
            raw={"schedule": entry.get("positionScheduleCodes") or [],
                 "offering": entry.get("positionOfferingCode") or "",
                 "regions": places.get(country) or []},
        )
