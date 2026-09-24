"""Arbeitnow — free, documented job-board API with strong coverage in the
German-speaking market and a growing set of remote listings.

Endpoint: https://www.arbeitnow.com/api/job-board-api
"""

from __future__ import annotations

from ..models import Job, Salary, WorkMode
from ..textutils import (
    detect_language,
    detect_remote_scope,
    extract_salary,
    parse_date,
    strip_html,
)
from .base import JobSource, SearchQuery

API = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 5


class ArbeitnowSource(JobSource):
    id = "arbeitnow"
    name = "Arbeitnow"
    homepage = "https://www.arbeitnow.com"
    tos_tier = "open"

    def search(self, query: SearchQuery) -> list[Job]:
        terms = [t.lower() for t in query.terms()]
        jobs: list[Job] = []
        for page in range(1, MAX_PAGES + 1):
            payload = self.fetcher.get_json(API, params={"page": page})
            entries = (payload or {}).get("data") or []
            if not entries:
                break
            for entry in entries:
                title = str(entry.get("title") or "")
                description = strip_html(str(entry.get("description") or ""))
                tags = " ".join(str(t) for t in (entry.get("tags") or []) if t)
                if terms and not any(t in f"{title} {tags} {description}".lower() for t in terms):
                    continue
                scope, regions = detect_remote_scope(description)
                salary = extract_salary(description, "EUR") or Salary()
                jobs.append(
                    self.make_job(
                        str(entry.get("slug") or ""),
                        title=title,
                        company=str(entry.get("company_name") or ""),
                        location=str(entry.get("location") or ""),
                        work_mode=WorkMode.REMOTE if entry.get("remote") else WorkMode.UNKNOWN,
                        remote_scope=scope,
                        remote_regions=regions,
                        url=str(entry.get("url") or ""),
                        posted_at=parse_date(entry.get("created_at")),
                        description=description,
                        language=detect_language(description),
                        salary=salary,
                        raw={"tags": entry.get("tags", []), "job_types": entry.get("job_types", [])},
                    )
                )
                if len(jobs) >= query.limit:
                    return jobs
        return jobs
