"""Jooble — aggregator with a free JSON API and worldwide coverage.

Free key: https://jooble.org/api/about (set ``JOOBLE_API_KEY``). The API is a
POST endpoint, one request per keyword and location pair.
"""

from __future__ import annotations

import os

from ..models import Job, Salary
from ..textutils import (
    detect_language,
    detect_remote_scope,
    detect_work_mode,
    extract_salary,
    parse_date,
    strip_html,
)
from .base import JobSource, SearchQuery

API = "https://jooble.org/api/{key}"


class JoobleSource(JobSource):
    id = "jooble"
    name = "Jooble"
    homepage = "https://jooble.org"
    tos_tier = "credentials"
    required_env = ("JOOBLE_API_KEY",)

    def search(self, query: SearchQuery) -> list[Job]:
        if not self.credentials_present():
            return []
        url = API.format(key=os.environ["JOOBLE_API_KEY"])
        locations = ["remote"] if query.remote_only else [*query.local_areas, ""]
        jobs: list[Job] = []
        for term in query.terms():
            for location in locations or [""]:
                payload = self.fetcher.post_json(url, {"keywords": term, "location": location})
                for entry in (payload or {}).get("jobs", []):
                    job = self._parse(entry)
                    if job:
                        jobs.append(job)
                    if len(jobs) >= query.limit:
                        return jobs
        return jobs

    def _parse(self, entry: dict) -> Job | None:
        description = strip_html(str(entry.get("snippet") or ""))
        location = str(entry.get("location") or "")
        scope, regions = detect_remote_scope(description)
        salary_str = str(entry.get("salary") or "") or description
        salary = extract_salary(salary_str) or Salary()
        return self.make_job(
            str(entry.get("id") or ""),
            title=str(entry.get("title") or ""),
            company=str(entry.get("company") or ""),
            location=location,
            work_mode=detect_work_mode(description, location),
            remote_scope=scope,
            remote_regions=regions,
            url=str(entry.get("link") or ""),
            posted_at=parse_date(entry.get("updated")),
            description=description,
            language=detect_language(description),
            salary=salary,
            raw={"jooble_source": entry.get("source", "")},
        )