"""InfoJobs (Spain) — **opt-in, restricted.**

InfoJobs is the highest signal-to-effort Spanish board: a large share of its
ads publish a salary band, the minimum years of experience, and an explicit
list of required skills, which map straight onto JobRadar's requirements model.

The listing page renders only a handful of cards server-side, but the raw HTML
contains every result as a ``/<city>/<slug>/of-i<hash>`` URL, and the slug
already carries the job title — so ads can be filtered by title *before*
spending a request on the detail page.

The listing and the ad page need different levels of ``Fetcher``'s browser
support: the listing answers a plain headless browser (``browser="dynamic"``)
normally, but the ad page answers the same request with an HTTP 405 behind a
CAPTCHA challenge — it needs ``browser="stealthy"``, which gets through.
"""

from __future__ import annotations

import re

from ...models import Job, Salary, WorkMode
from ...textutils import (
    detect_language,
    extract_min_years,
    extract_salary,
    normalise,
    parse_date,
    strip_html,
)
from ..base import JobSource, SearchQuery

SEARCH = "https://www.infojobs.net/jobsearch/search-results/list.xhtml"
OFFER_URL = re.compile(r"//www\.infojobs\.net/([a-z0-9-]+)/([a-z0-9-]+)/of-i([0-9a-f]+)", re.I)
COMPANY_META = re.compile(r'<meta name="description" content="[^"]*?en la empresa ([^".]+)', re.I)
CLOSED_PATH = "/candidate/offer-no-accesible/"


class InfoJobsSource(JobSource):
    id = "infojobs"
    name = "InfoJobs"
    homepage = "https://www.infojobs.net"
    tos_tier = "restricted"
    tos_note = (
        "InfoJobs' terms of use restrict automated collection of its listings. "
        "InfoJobs also publishes an official partner API — if you can get a key, "
        "prefer it. Enabling this adapter is your decision and your responsibility."
    )
    supports_remote_filter = True

    def search(self, query: SearchQuery) -> list[Job]:
        jobs: dict[str, Job] = {}
        wanted = [normalise(t) for t in query.terms()]
        for term in query.terms():
            params = {"keyword": term, "sinceDate": self._since(query.max_age_days)}
            if query.remote_only:
                params["teleworkingIds"] = "2"  # fully remote
            body = self.fetcher.get(SEARCH, params=params, browser="dynamic")
            if not body:
                continue
            for city, slug, offer_hash in OFFER_URL.findall(body):
                # Filter on the slug before paying for a detail request.
                if wanted and not any(
                    any(word in normalise(str(slug)) for word in term.split()) for term in wanted
                ):
                    continue
                url = f"https://www.infojobs.net/{city}/{slug}/of-i{offer_hash}"
                if offer_hash in jobs:
                    continue
                job = self._detail(offer_hash, url, str(slug), str(city))
                if job:
                    jobs[offer_hash] = job
                if len(jobs) >= query.limit:
                    return list(jobs.values())
        return list(jobs.values())

    @staticmethod
    def _since(days: int) -> str:
        if days <= 1:
            return "_24_HOURS"
        if days <= 7:
            return "_7_DAYS"
        return "_15_DAYS"

    def _detail(self, offer_hash: str, url: str, slug: str, city: str) -> Job | None:
        body = self.fetcher.get(url, browser="stealthy")
        if not body:
            return None
        text = strip_html(str(body))
        company_match = COMPANY_META.search(body)
        title = str(slug).replace("-", " ").strip().title()
        remote = "solo teletrabajo" in text.lower()
        salary = extract_salary(text, "EUR") or Salary()
        return self.make_job(
            offer_hash,
            title=title,
            company=str(company_match.group(1)).strip() if company_match else "",
            location=str(city).replace("-", " ").title(),
            country="ES",
            work_mode=WorkMode.REMOTE if remote else WorkMode.UNKNOWN,
            url=url,
            posted_at=parse_date(self._posted(text)),
            description=text,
            language=detect_language(text) or "es",
            salary=salary,
            min_years_experience=extract_min_years(text),
            raw={"skills": self._skills(text)},
        )

    @staticmethod
    def _posted(text: str) -> str:
        match = re.search(r"[Hh]ace\s+(\d+)\s*([dhm])", text)
        return f"{match.group(1)}{match.group(2)}" if match else ""

    @staticmethod
    def _skills(text: str) -> list[str]:
        """InfoJobs' 'Conocimientos necesarios' block, ready to become reqs."""
        match = re.search(r"Conocimientos necesarios(.{0,600})", text, re.S | re.I)
        if not match:
            return []
        chunk = match.group(1)
        return [str(s).strip(" •-") for s in re.split(r"[•\n]", chunk) if 2 < len(str(s).strip()) < 40][:15]

    def check_open(self, job: Job) -> tuple[bool, str]:
        """A closed InfoJobs ad redirects; the visible title stays the same.

        The redirect is the reliable signal, not the page text.
        """
        body = self.fetcher.get(job.link, use_cache=False, browser="stealthy")
        if body is None:
            return False, "Offer page unreachable"
        if CLOSED_PATH in body or "ya no se aceptan más candidaturas" in body.lower():
            return False, "No longer accepting applications"
        return True, ""