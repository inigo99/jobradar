"""Adzuna — aggregator with an official API covering ~20 countries.

Free developer keys: https://developer.adzuna.com/ (set ``ADZUNA_APP_ID`` and
``ADZUNA_APP_KEY``). Adzuna is the most useful *national* source in the default
set because it indexes local boards and company sites in each country, which is
the coverage a purely remote-first aggregator cannot give.
"""

from __future__ import annotations

import os

from ..config import country_info
from ..models import Job, Salary, SalaryOrigin, WorkMode
from ..textutils import (
    detect_language,
    detect_remote_scope,
    detect_work_mode,
    parse_date,
    strip_html,
)
from .base import JobSource, SearchQuery

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
PAGE_SIZE = 50


class AdzunaSource(JobSource):
    id = "adzuna"
    name = "Adzuna"
    homepage = "https://www.adzuna.com"
    tos_tier = "credentials"
    required_env = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")

    def search(self, query: SearchQuery) -> list[Job]:
        if not self.credentials_present():
            return []
        app_id = os.environ["ADZUNA_APP_ID"]
        app_key = os.environ["ADZUNA_APP_KEY"]

        jobs: list[Job] = []
        for country in query.countries or ["gb"]:
            code = country_info(country).get("adzuna")
            if not code:
                continue  # Adzuna does not cover this country
            for term in query.terms():
                params = {
                    "app_id": app_id,
                    "app_key": app_key,
                    "results_per_page": PAGE_SIZE,
                    "what": term,
                    "max_days_old": max(1, query.max_age_days),
                    "content-type": "application/json",
                }
                if query.remote_only:
                    params["what_or"] = "remote teletrabajo télétravail"
                payload = self.fetcher.get_json(API.format(country=code, page=1), params=params)
                for entry in (payload or {}).get("results", []):
                    job = self._parse(entry, country.upper())
                    if job:
                        jobs.append(job)
                    if len(jobs) >= query.limit:
                        return jobs
        return jobs

    def _parse(self, entry: dict, country: str) -> Job | None:
        description = strip_html(entry.get("description", ""))
        title = entry.get("title", "")
        location = (entry.get("location") or {}).get("display_name", "")
        salary = Salary()
        if entry.get("salary_min"):
            salary = Salary(
                minimum=int(entry["salary_min"]),
                maximum=int(entry.get("salary_max") or entry["salary_min"]),
                currency=country_info(country).get("currency", "EUR"),
                origin=SalaryOrigin.PUBLISHED
                if entry.get("salary_is_predicted") not in ("1", 1, True)
                else SalaryOrigin.ESTIMATED,
                basis="From Adzuna; flagged as predicted when Adzuna estimated it.",
            )
        scope, regions = detect_remote_scope(description)
        return self.make_job(
            entry.get("id", ""),
            title=title,
            company=(entry.get("company") or {}).get("display_name", ""),
            location=location,
            country=country,
            work_mode=detect_work_mode(description, location) or WorkMode.UNKNOWN,
            remote_scope=scope,
            remote_regions=regions,
            url=entry.get("redirect_url", ""),
            posted_at=parse_date(entry.get("created")),
            description=description,
            language=detect_language(description),
            salary=salary,
            raw={"category": (entry.get("category") or {}).get("label", "")},
        )
