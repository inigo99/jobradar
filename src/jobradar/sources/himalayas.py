"""Himalayas — public JSON API for remote jobs.

Endpoint: https://himalayas.app/jobs/api?limit=20&offset=0

Himalayas is the one aggregator that publishes structured geographic
restrictions (``locationRestrictions`` / ``timezoneRestrictions``), which is
exactly the field that decides whether an international remote job is real for
a given candidate. That makes it disproportionately valuable even though its
raw volume is modest.
"""

from __future__ import annotations

from ..models import Job, RemoteScope, Salary, SalaryOrigin, WorkMode
from ..textutils import detect_language, parse_date, strip_html
from .base import JobSource, SearchQuery

API = "https://himalayas.app/jobs/api"
PAGE_SIZE = 20


class HimalayasSource(JobSource):
    id = "himalayas"
    name = "Himalayas"
    homepage = "https://himalayas.app"
    tos_tier = "open"
    supports_remote_filter = True

    def search(self, query: SearchQuery) -> list[Job]:
        terms = [t.lower() for t in query.terms()]
        jobs: list[Job] = []
        seen: set[str] = set()
        for offset in range(0, min(query.limit * 4, 400), PAGE_SIZE):
            payload = self.fetcher.get_json(API, params={"limit": PAGE_SIZE, "offset": offset})
            entries = (payload or {}).get("jobs") or []
            if not entries:
                break
            for entry in entries:
                job = self._parse(entry, terms)
                if job and job.id not in seen:
                    seen.add(job.id)
                    jobs.append(job)
                if len(jobs) >= query.limit:
                    return jobs
        return jobs

    def _parse(self, entry: dict, terms: list[str]) -> Job | None:
        title = entry.get("title", "")
        description = strip_html(entry.get("description") or entry.get("excerpt") or "")
        if terms and not any(t in f"{title} {description}".lower() for t in terms):
            return None

        restrictions = [str(r) for r in (entry.get("locationRestrictions") or [])]
        timezones = [str(t) for t in (entry.get("timezoneRestrictions") or [])]
        if not restrictions:
            scope, regions = RemoteScope.WORLDWIDE, []
        elif len(restrictions) > 6:
            scope, regions = RemoteScope.REGION, restrictions
        else:
            scope, regions = RemoteScope.COUNTRY, restrictions

        salary = Salary()
        if entry.get("minSalary") and entry.get("maxSalary"):
            salary = Salary(
                minimum=int(entry["minSalary"]),
                maximum=int(entry["maxSalary"]),
                currency=(entry.get("salaryCurrency") or "USD").upper(),
                origin=SalaryOrigin.PUBLISHED,
                basis="Published on Himalayas.",
            )

        native_id = str(entry.get("guid") or entry.get("id") or entry.get("applicationLink", ""))[:80]
        return self.make_job(
            native_id,
            title=title,
            company=entry.get("companyName", ""),
            location=", ".join(restrictions) or "Remote",
            work_mode=WorkMode.REMOTE,
            remote_scope=scope,
            remote_regions=regions or timezones,
            url=entry.get("applicationLink") or entry.get("url", ""),
            posted_at=parse_date(entry.get("pubDate")),
            description=description,
            language=detect_language(description),
            salary=salary,
            raw={"timezones": timezones, "seniority": entry.get("seniority")},
        )
