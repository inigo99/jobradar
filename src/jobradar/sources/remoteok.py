"""RemoteOK — public JSON feed of remote-only jobs.

Docs: https://remoteok.com/api (the first element of the array is a legal
notice, not a job; it also states the attribution requirement, which the
dashboard honours by always linking back to the original ad).
"""

from __future__ import annotations

from ..models import Job, RemoteScope, Salary, SalaryOrigin, WorkMode
from ..textutils import detect_language, detect_remote_scope, parse_date, strip_html
from .base import JobSource, SearchQuery

API = "https://remoteok.com/api"


class RemoteOKSource(JobSource):
    id = "remoteok"
    name = "RemoteOK"
    homepage = "https://remoteok.com"
    tos_tier = "open"
    supports_remote_filter = True

    def search(self, query: SearchQuery) -> list[Job]:
        payload = self.fetcher.get_json(API)
        if not isinstance(payload, list):
            return []
        terms = [t.lower() for t in query.terms()]
        jobs: list[Job] = []
        for entry in payload:
            if not isinstance(entry, dict) or "position" not in entry:
                continue  # the legal notice element
            title = entry.get("position", "")
            tags = " ".join(entry.get("tags") or [])
            haystack = f"{title} {tags} {entry.get('description', '')}".lower()
            if terms and not any(term in haystack for term in terms):
                continue

            description = strip_html(entry.get("description", ""))
            scope, regions = detect_remote_scope(f"{description} {entry.get('location', '')}")
            salary = Salary()
            if entry.get("salary_min") and entry.get("salary_max"):
                salary = Salary(
                    minimum=int(entry["salary_min"]),
                    maximum=int(entry["salary_max"]),
                    currency="USD",
                    origin=SalaryOrigin.PUBLISHED,
                    basis="Published on RemoteOK.",
                )
            jobs.append(
                self.make_job(
                    entry.get("id") or entry.get("slug"),
                    title=title,
                    company=entry.get("company", ""),
                    location=entry.get("location") or "Remote",
                    work_mode=WorkMode.REMOTE,
                    remote_scope=scope if scope != RemoteScope.UNKNOWN else RemoteScope.UNKNOWN,
                    remote_regions=regions,
                    url=entry.get("url", ""),
                    apply_url=entry.get("apply_url", ""),
                    posted_at=parse_date(entry.get("date") or entry.get("epoch")),
                    description=description,
                    language=detect_language(description),
                    salary=salary,
                    raw={"tags": entry.get("tags", [])},
                )
            )
            if len(jobs) >= query.limit:
                break
        return jobs
