"""LinkedIn — guest job-search endpoint. **Opt-in, restricted.**

Reads the unauthenticated endpoint that powers LinkedIn's public job widget.
It returns a fragment of HTML rather than JSON, so the parsing here is regex
over ``data-entity-urn`` attributes: a DOM parser is not usable because the
fragment is not a document.

Read ``tos_note`` before enabling this. LinkedIn's User Agreement restricts
automated access to the service; enabling this adapter is a decision only the
person running JobRadar can make for themselves.
"""

from __future__ import annotations

import re

from ...models import Job, Salary, WorkMode
from ...textutils import (
    detect_language,
    detect_remote_scope,
    detect_work_mode,
    extract_min_years,
    extract_salary,
    parse_date,
    strip_html,
)
from ..base import JobSource, SearchQuery

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

CARD = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"(.*?)(?=data-entity-urn|\Z)', re.S)
TITLE = re.compile(r'class="[^"]*base-search-card__title[^"]*"[^>]*>\s*(.*?)\s*<', re.S)
COMPANY = re.compile(r'class="[^"]*base-search-card__subtitle[^"]*"[^>]*>.*?>\s*(.*?)\s*<', re.S)
LOCATION = re.compile(r'class="[^"]*job-search-card__location[^"]*"[^>]*>\s*(.*?)\s*<', re.S)
POSTED = re.compile(r'datetime="([\d-]+)"')

CLOSED_MARKERS = re.compile(
    r"no longer accepting applications|ya no se aceptan solicitudes|closed-job", re.I
)


class LinkedInGuestSource(JobSource):
    id = "linkedin"
    name = "LinkedIn (guest endpoint)"
    homepage = "https://www.linkedin.com/jobs"
    tos_tier = "restricted"
    tos_note = (
        "LinkedIn's User Agreement restricts automated access, including scraping of "
        "public pages. Enabling this adapter is your decision and your responsibility; "
        "keep the request delay high and the volume comparable to browsing by hand."
    )
    supports_remote_filter = True
    required_env = ()

    #: LinkedIn's own filter values.
    REMOTE_FILTER = "2"

    def search(self, query: SearchQuery) -> list[Job]:
        jobs: dict[str, Job] = {}
        # `f_TPR` is a recency window in seconds; ask for exactly what we need.
        recency = f"r{max(1, query.max_age_days) * 86400}"
        locations = self._locations(query)
        for term in query.terms():
            for location, remote in locations:
                for start in range(0, min(query.limit, 100), 25):
                    params = {
                        "keywords": term,
                        "location": location,
                        "f_TPR": recency,
                        "start": start,
                    }
                    if remote:
                        params["f_WT"] = self.REMOTE_FILTER
                    body = self.fetcher.get(SEARCH, params=params)
                    if not body:
                        break
                    found = self._parse_cards(body)
                    if not found:
                        break
                    for job in found:
                        jobs.setdefault(job.id, job)
                    if len(jobs) >= query.limit:
                        return list(jobs.values())[: query.limit]
        return list(jobs.values())

    def _locations(self, query: SearchQuery) -> list[tuple[str, bool]]:
        """(location string, remote-filter) pairs to search.

        Remote roles are searched with LinkedIn's remote filter and a national
        location; the user's own areas are searched *without* it, because
        that is the only way hybrid and on-site local jobs show up.
        """
        from ...config import country_info

        pairs: list[tuple[str, bool]] = []
        for code in query.countries or []:
            pairs.append((country_info(code).get("name", code), True))
        if not pairs:
            pairs.append(("", True))
        for area in query.local_areas:
            pairs.append((area, False))
        return pairs

    def _parse_cards(self, html: str) -> list[Job]:
        jobs: list[Job] = []
        for job_id, card in CARD.findall(html):
            title = self._first(TITLE, card)
            if not title:
                continue
            location = self._first(LOCATION, card)
            jobs.append(
                self.make_job(
                    job_id,
                    title=title,
                    company=self._first(COMPANY, card),
                    location=location,
                    work_mode=WorkMode.REMOTE if "remote" in location.lower() else WorkMode.UNKNOWN,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                    posted_at=parse_date(self._first(POSTED, card)),
                )
            )
        return jobs

    @staticmethod
    def _first(pattern: re.Pattern[str], text: str) -> str:
        match = pattern.search(text)
        return strip_html(match.group(1)).strip() if match else ""

    def fetch_description(self, job: Job) -> str:
        """Pull the full ad text, which is where the truth about remote lives.

        LinkedIn's remote tag is wrong often enough that the pipeline always
        re-derives work mode from this text.
        """
        body = self.fetcher.get(DETAIL.format(job_id=job.native_id))
        if not body:
            return job.description
        text = strip_html(body)
        job.description = text
        job.language = detect_language(text)
        job.work_mode = detect_work_mode(text, job.location) or job.work_mode
        job.remote_scope, job.remote_regions = detect_remote_scope(text)
        job.min_years_experience = extract_min_years(text)
        job.salary = extract_salary(text) or job.salary or Salary()
        return text

    def check_open(self, job: Job) -> tuple[bool, str]:
        body = self.fetcher.get(DETAIL.format(job_id=job.native_id), use_cache=False)
        if body is None:
            status = self.fetcher.head_status(job.link)
            return (False, "HTTP 404") if status == 404 else (True, "")
        if CLOSED_MARKERS.search(body):
            return False, "No longer accepting applications"
        return True, ""
