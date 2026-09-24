"""Indeed — public search pages, read through a browser. **Opt-in, restricted.**

Indeed has no public job-search API. Its search page (``/jobs?q=...``) is
served behind a bot check, so every request goes through ``Fetcher`` with
``browser="stealthy"``. Indeed runs one site per country
(``es.indeed.com``, ``uk.indeed.com``...), picked here from the countries the
user may work from.

Each results page embeds its cards twice: as HTML, and as a JSON object
assigned to ``window.mosaic.providerData["mosaic-provider-jobcards"]``. The
JSON is read first — it carries the job key, title, company, location, a
relative age and, when published, a salary — and the HTML cards (``data-jk``
attributes) are the fallback if the page layout changes. The ad page
(``/viewjob?jk=<key>``) holds the full text in ``#jobDescriptionText``.

Indeed returns many old ads for any query: the recency parameter
(``fromage``, in days) is always sent, and the freshness filter still applies
afterwards. Read ``tos_note`` before enabling this adapter.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any

from ...models import Job, Salary, SalaryOrigin, WorkMode
from ...textutils import detect_language, parse_date, strip_html
from ..base import JobSource, SearchQuery

#: Indeed's site per ISO country code; anything else falls back to the US site.
COUNTRY_SITES = {
    "ES": "es", "GB": "uk", "UK": "uk", "IE": "ie", "DE": "de", "AT": "at", "CH": "ch",
    "FR": "fr", "BE": "be", "NL": "nl", "IT": "it", "PT": "pt", "PL": "pl", "SE": "se",
    "MX": "mx", "AR": "ar", "CO": "co", "CL": "cl", "BR": "br", "CA": "ca", "AU": "au",
    "NZ": "nz", "IN": "in", "SG": "sg", "US": "www",
}
PAGE_SIZE = 10
MAX_PAGES = 3

MOSAIC = re.compile(
    r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});\s*\n', re.S
)
CARD_KEY = re.compile(r'data-jk="([0-9a-f]{8,})"')
CARD_TITLE = re.compile(r'<span[^>]*title="([^"]+)"', re.S)
CARD_COMPANY = re.compile(r'data-testid="company-name"[^>]*>(.*?)</span>', re.S)
CARD_LOCATION = re.compile(r'data-testid="text-location"[^>]*>(.*?)</div>', re.S)
DESCRIPTION = re.compile(r'id="jobDescriptionText"[^>]*>(.*?)</div>\s*(?:</div>|<div)', re.S)
EXPIRED = re.compile(r"This job has expired|Esta oferta de empleo ha caducado|job is no longer "
                     r"available|ya no está disponible", re.I)
#: Indeed's salary periods, to annualise a published figure.
PERIOD_FACTORS = {"YEARLY": 1, "MONTHLY": 12, "WEEKLY": 52, "DAILY": 230, "HOURLY": 1760}


def site_for(country: str) -> str:
    return f"https://{COUNTRY_SITES.get((country or '').upper(), 'www')}.indeed.com"


def cards_from_mosaic(html: str) -> list[dict[str, Any]]:
    """The embedded JSON results of one page, or [] when it is not there."""
    match = MOSAIC.search(html or "")
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    results = (((data.get("metaData") or {}).get("mosaicProviderJobCardsModel") or {})
               .get("results")) or []
    return [r for r in results if isinstance(r, dict) and r.get("jobkey")]


def cards_from_html(html: str) -> list[dict[str, Any]]:
    """Fallback: the same cards read from the HTML."""
    cards: list[dict[str, Any]] = []
    chunks = re.split(r"(?=data-jk=\")", html or "")
    for chunk in chunks:
        key = CARD_KEY.search(chunk)
        title = CARD_TITLE.search(chunk)
        if not key or not title:
            continue
        company = CARD_COMPANY.search(chunk)
        location = CARD_LOCATION.search(chunk)
        cards.append({
            "jobkey": key.group(1),
            "title": strip_html(title.group(1)),
            "company": strip_html(company.group(1)) if company else "",
            "formattedLocation": strip_html(location.group(1)) if location else "",
        })
    return cards


def posted_date(card: dict[str, Any]) -> date | None:
    """Publication date: ``pubDate`` is epoch milliseconds in the embedded JSON."""
    stamp = card.get("pubDate")
    if isinstance(stamp, (int, float)) and stamp > 0:
        try:
            return datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    return parse_date(card.get("formattedRelativeTime"))


def salary_from(card: dict[str, Any]) -> Salary:
    """A published salary, annualised, or an empty band."""
    extracted = card.get("extractedSalary") or {}
    try:
        figures = [float(v) for v in (extracted.get("min"), extracted.get("max")) if v]
    except (TypeError, ValueError):
        return Salary()
    if not figures:
        return Salary()
    factor = PERIOD_FACTORS.get(str(extracted.get("type", "YEARLY")).upper(), 1)
    minimum, maximum = int(min(figures) * factor), int(max(figures) * factor)
    currency = str((card.get("salarySnippet") or {}).get("currency") or "EUR").upper()
    return Salary(minimum=minimum, maximum=maximum, currency=currency,
                  origin=SalaryOrigin.PUBLISHED, basis="Published on Indeed.")


class IndeedSource(JobSource):
    id = "indeed"
    name = "Indeed"
    homepage = "https://www.indeed.com"
    tos_tier = "restricted"
    tos_note = (
        "Indeed's terms of service prohibit scraping its site. Enabling this adapter is "
        "your decision and your responsibility; keep the request delay high and the "
        "volume comparable to browsing by hand."
    )
    supports_remote_filter = False

    def search(self, query: SearchQuery) -> list[Job]:
        jobs: dict[str, Job] = {}
        countries = query.countries or ["US"]
        places = [("", country) for country in countries]
        places += [(area, countries[0]) for area in query.local_areas]
        for term in query.terms():
            for place, country in places:
                site = site_for(country)
                for page in range(MAX_PAGES):
                    params = {"q": term, "l": place, "fromage": max(1, query.max_age_days),
                              "start": page * PAGE_SIZE, "sort": "date"}
                    if query.remote_only and not place:
                        params["sc"] = "0kf:attr(DSQF7);"  # Indeed's "remote" filter
                    body = self.get(f"{site}/jobs", params=params, browser="stealthy")
                    if not body:
                        break
                    cards = cards_from_mosaic(body) or cards_from_html(body)
                    if not cards:
                        break
                    for card in cards:
                        job = self._parse(card, site, country)
                        jobs.setdefault(job.id, job)
                    if len(jobs) >= query.limit:
                        return list(jobs.values())[: query.limit]
        return list(jobs.values())

    def _parse(self, card: dict[str, Any], site: str, country: str) -> Job:
        key = str(card["jobkey"])
        location = str(card.get("formattedLocation") or "")
        remote = bool(card.get("remoteLocation")) or "remote" in location.lower() \
            or "remoto" in location.lower()
        snippet = strip_html(str(card.get("snippet") or ""))
        return self.make_job(
            key,
            title=str(card.get("title") or card.get("displayTitle") or ""),
            company=str(card.get("company") or ""),
            location=location,
            country=(country or "").upper()[:2],
            work_mode=WorkMode.REMOTE if remote else WorkMode.UNKNOWN,
            url=f"{site}/viewjob?jk={key}",
            posted_at=posted_date(card),
            description=snippet,
            salary=salary_from(card),
            raw={"site": site},
        )

    def fetch_description(self, job: Job) -> str:
        body = self.get(job.link, browser="stealthy")
        if not body:
            return job.description or ""
        match = DESCRIPTION.search(body)
        text = strip_html(match.group(1) if match else body)
        job.language = detect_language(text, job.language)
        return text

    def check_open(self, job: Job) -> tuple[bool, str]:
        body = self.get(job.link, use_cache=False, browser="stealthy")
        if body is None:
            return True, ""  # a blocked page is not evidence of closure
        if EXPIRED.search(body):
            return False, "The ad says it has expired"
        return True, ""
