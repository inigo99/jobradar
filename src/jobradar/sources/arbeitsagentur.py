"""Bundesagentur für Arbeit — Germany's public employment service.

The largest job database in Germany, and one of the few public boards that
covers every kind of work: nursing, teaching, trades, care, retail, offices,
apprenticeships. Its search is a JSON API the agency's own site and app use,
with a public client id; https://jobsuche.api.bund.dev documents it.

It only runs when Germany is one of the countries you search: the search sends
the title, and the ads come back without their text, which is fetched later,
one request per ad, only for the ads that survive the filters.
"""

from __future__ import annotations

import base64

from ..models import Job
from ..textutils import parse_date, strip_html
from .base import JobSource, SearchQuery

SEARCH = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
DETAILS = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{code}"
AD_PAGE = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
#: The public client id the agency's own job search sends.
HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
PAGE_SIZE = 50
#: The API accepts "published in the last N days" up to 100.
MAX_AGE_DAYS = 100
#: angebotsart=1: employment (not self-employment, apprenticeships or internships).
EMPLOYMENT = 1
#: arbeitszeit=ho: working from home.
HOME_OFFICE = "ho"


class ArbeitsagenturSource(JobSource):
    id = "arbeitsagentur"
    name = "Bundesagentur für Arbeit"
    homepage = "https://www.arbeitsagentur.de/jobsuche/"
    tos_tier = "open"
    tos_note = ("Public JSON API behind the agency's own job search, with a public client id; "
                "documented by the community at jobsuche.api.bund.dev, not by the agency.")

    def search(self, query: SearchQuery) -> list[Job]:
        if "DE" not in {country.upper() for country in query.countries}:
            return []
        jobs: list[Job] = []
        seen: set[str] = set()
        for term in query.terms():
            params: dict[str, object] = {
                "was": term,
                "angebotsart": EMPLOYMENT,
                "veroeffentlichtseit": min(MAX_AGE_DAYS, max(1, query.max_age_days)),
                "size": PAGE_SIZE,
                "page": 1,
            }
            if query.remote_only:
                params["arbeitszeit"] = HOME_OFFICE
            payload = self.fetcher.get_json(SEARCH, params=params, headers=HEADERS)
            for entry in (payload or {}).get("stellenangebote") or []:
                job = self._parse(entry)
                if job is None or job.native_id in seen:
                    continue
                seen.add(job.native_id)
                jobs.append(job)
                if len(jobs) >= query.limit:
                    return jobs
        return jobs

    def _parse(self, entry: dict) -> Job | None:
        refnr = str(entry.get("refnr") or entry.get("referenznummer") or "")
        if not refnr:
            return None
        place = entry.get("arbeitsort") or {}
        location = ", ".join(str(part) for part in (place.get("ort"), place.get("region"))
                             if part)
        return self.make_job(
            refnr,
            title=str(entry.get("titel") or entry.get("beruf") or ""),
            company=str(entry.get("arbeitgeber") or ""),
            location=location,
            country="DE",
            url=AD_PAGE.format(refnr=refnr),
            apply_url=str(entry.get("externeUrl") or ""),
            posted_at=parse_date(entry.get("aktuelleVeroeffentlichungsdatum")),
            # Ads come without text until fetch_description; German is the norm.
            language="de",
            raw={"occupation": entry.get("beruf") or "",
                 "start": entry.get("eintrittsdatum") or ""},
        )

    def fetch_description(self, job: Job) -> str:
        """The ad's text, from the details endpoint (one request per ad)."""
        code = base64.b64encode(job.native_id.encode()).decode()
        details = self.fetcher.get_json(DETAILS.format(code=code), headers=HEADERS) or {}
        text = details.get("stellenangebotsBeschreibung") or details.get("stellenbeschreibung")
        pay = details.get("verguetung")
        parts = [strip_html(str(text)) if text else "", f"Vergütung: {pay}" if pay else ""]
        return "\n\n".join(part for part in parts if part) or job.description or ""
