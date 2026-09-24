"""Company career boards (applicant tracking systems).

This is how JobRadar covers "search these specific companies too". Rather than
scraping a company's careers page, it talks to the public JSON board API of
whichever ATS the company uses. Those endpoints exist precisely so that job
aggregators can read them, they are stable, and they return structured data
including the full ad text — far better input than parsed HTML.

Users add entries to ``settings.sources.company_domains`` in either form:

``greenhouse:airbnb``  explicit provider and board slug
``stripe.com``         a bare domain, whose ATS is auto-detected once and cached

Supported: Greenhouse, Lever, Ashby, Workable, Recruitee, SmartRecruiters and
Personio, which together cover the large majority of startup and scale-up
hiring. Adding another is a dict entry plus a parser function.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ..models import Job, Salary, SalaryOrigin, WorkMode
from ..textutils import (
    detect_language,
    detect_remote_scope,
    detect_work_mode,
    extract_salary,
    parse_date,
    strip_html,
)
from .base import JobSource, SearchQuery

# provider -> URL template for the board's job list
BOARD_URLS: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
    "personio": "https://{slug}.jobs.personio.de/search.json",
}

# Patterns that reveal which ATS a company uses when its careers page is read.
DETECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "greenhouse": re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I),
    "lever": re.compile(r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_-]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)", re.I),
    "workable": re.compile(r"apply\.workable\.com/([a-z0-9_-]+)", re.I),
    "recruitee": re.compile(r"([a-z0-9_-]+)\.recruitee\.com", re.I),
    "smartrecruiters": re.compile(r"careers\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I),
    "personio": re.compile(r"([a-z0-9_-]+)\.jobs\.personio\.(?:de|com)", re.I),
}

CAREER_PATHS = ("/careers", "/jobs", "/careers/", "/company/careers", "/about/careers", "/")


class CompanyBoardsSource(JobSource):
    """Reads the ATS board of every company the user listed in settings."""

    id = "company_boards"
    name = "Company career boards"
    homepage = ""
    tos_tier = "open"

    def search(self, query: SearchQuery) -> list[Job]:
        entries: list[str] = list(self.options.get("company_domains") or [])
        terms = [t.lower() for t in query.terms()]
        jobs: list[Job] = []
        for entry in entries:
            provider, slug = self._resolve(entry)
            if not provider or not slug:
                continue
            for job in self._fetch_board(provider, slug, entry):
                haystack = f"{job.title} {job.description}".lower()
                if terms and not any(term in haystack for term in terms):
                    continue
                jobs.append(job)
                if len(jobs) >= query.limit:
                    return jobs
        return jobs

    # -- provider resolution ----------------------------------------------

    def _resolve(self, entry: str) -> tuple[str | None, str | None]:
        """Turn a settings entry into ``(provider, slug)``."""
        entry = entry.strip()
        if ":" in entry and not entry.startswith("http"):
            provider, _, slug = entry.partition(":")
            provider = provider.lower().strip()
            if provider in BOARD_URLS:
                return provider, slug.strip()
        return self._detect(entry)

    def _detect(self, domain: str) -> tuple[str | None, str | None]:
        """Find which ATS ``domain`` uses by reading its careers page.

        Cached by the fetcher, so this costs at most a couple of requests the
        first time a company is added and nothing afterwards.
        """
        host = re.sub(r"^https?://", "", domain).strip("/").split("/")[0]
        if not host:
            return None, None
        for path in CAREER_PATHS:
            body = self.fetcher.get(f"https://{host}{path}")
            if not body:
                continue
            for provider, pattern in DETECTION_PATTERNS.items():
                match = pattern.search(body)
                if match:
                    return provider, match.group(1)
        # Last resort: guess the slug from the domain and probe each board.
        guess = re.sub(r"[^a-z0-9]", "", host.split(".")[0].lower())
        for provider, template in BOARD_URLS.items():
            if self.fetcher.get_json(template.format(slug=guess)):
                return provider, guess
        return None, None

    # -- board readers -----------------------------------------------------

    def _fetch_board(self, provider: str, slug: str, label: str) -> list[Job]:
        payload = self.fetcher.get_json(BOARD_URLS[provider].format(slug=slug))
        if payload is None:
            return []
        parser: Callable[[Any, str, str], list[Job]] = getattr(self, f"_parse_{provider}")
        try:
            return parser(payload, slug, label)
        except (KeyError, TypeError, ValueError):
            return []

    def _job(self, provider: str, slug: str, native_id: str, **fields: Any) -> Job:
        job = Job(source=self.id, native_id=f"{provider}-{slug}-{native_id}", **fields)
        job.raw.setdefault("ats", provider)
        return job.ensure_id()

    @staticmethod
    def _company_from(slug: str, label: str) -> str:
        pretty = re.sub(r"[-_]+", " ", str(slug)).strip().title()
        return pretty or label

    def _parse_greenhouse(self, payload: dict, slug: str, label: str) -> list[Job]:
        jobs = []
        for entry in payload.get("jobs", []):
            description = strip_html(str(entry.get("content") or ""))
            location = str((entry.get("location") or {}).get("name") or "")
            jobs.append(self._make(
                "greenhouse", slug, str(entry.get("id") or ""), str(entry.get("title") or ""),
                self._company_from(slug, label), location, str(entry.get("absolute_url") or ""),
                entry.get("updated_at") or entry.get("first_published"), description))
        return jobs

    def _parse_lever(self, payload: list, slug: str, label: str) -> list[Job]:
        jobs = []
        for entry in payload:
            categories = entry.get("categories") or {}
            description = str(entry.get("descriptionPlain") or strip_html(str(entry.get("description") or "")))
            extra = " ".join(
                strip_html(str(item.get("content") or "")) for item in (entry.get("lists") or []) if isinstance(item, dict)
            )
            jobs.append(self._make(
                "lever", slug, str(entry.get("id") or ""), str(entry.get("text") or ""),
                self._company_from(slug, label), str(categories.get("location") or ""),
                str(entry.get("hostedUrl") or ""), entry.get("createdAt"),
                f"{description}\n\n{extra}".strip()))
        return jobs

    def _parse_ashby(self, payload: dict, slug: str, label: str) -> list[Job]:
        jobs = []
        for entry in payload.get("jobs", []):
            desc_raw = str(entry.get("descriptionPlain") or strip_html(str(entry.get("descriptionHtml") or "")))
            job = self._make(
                "ashby", slug, str(entry.get("id") or ""), str(entry.get("title") or ""),
                self._company_from(slug, label), str(entry.get("location") or ""),
                str(entry.get("jobUrl") or ""), entry.get("publishedAt"),
                desc_raw)
            if entry.get("isRemote"):
                job.work_mode = WorkMode.REMOTE
            compensation = entry.get("compensation") or {}
            summary = compensation.get("compensationTierSummary")
            if summary:
                parsed = extract_salary(str(summary))
                if parsed:
                    parsed.basis = f"Published on the Ashby board: {summary}"
                    job.salary = parsed
            jobs.append(job)
        return jobs

    def _parse_workable(self, payload: dict, slug: str, label: str) -> list[Job]:
        jobs = []
        company = str(payload.get("name") or self._company_from(slug, label))
        for entry in payload.get("jobs", []):
            location = ", ".join(
                filter(None, [str((entry.get("location") or {}).get("city") or ""),
                              str((entry.get("location") or {}).get("country") or "")])
            )
            description = strip_html(
                f"{entry.get('description', '')}\n{entry.get('requirements', '')}"
            )
            jobs.append(self._make(
                "workable", slug, str(entry.get("shortcode") or ""), str(entry.get("title") or ""),
                company, location, str(entry.get("url") or ""),
                entry.get("published_on"), description))
        return jobs

    def _parse_recruitee(self, payload: dict, slug: str, label: str) -> list[Job]:
        jobs = []
        for entry in payload.get("offers", []):
            description = strip_html(
                f"{entry.get('description', '')}\n{entry.get('requirements', '')}"
            )
            jobs.append(self._make(
                "recruitee", slug, str(entry.get("id") or ""), str(entry.get("title") or ""),
                self._company_from(slug, label), str(entry.get("location") or ""),
                str(entry.get("careers_url") or entry.get("careers_apply_url") or ""),
                entry.get("published_at") or entry.get("created_at"), description))
        return jobs

    def _parse_smartrecruiters(self, payload: dict, slug: str, label: str) -> list[Job]:
        jobs = []
        for entry in payload.get("content", []):
            location = entry.get("location") or {}
            place = ", ".join(filter(None, [str(location.get("city") or ""), str(location.get("country") or "")]))
            job = self._make(
                "smartrecruiters", slug, str(entry.get("id") or ""), str(entry.get("name") or ""),
                str((entry.get("company") or {}).get("name") or self._company_from(slug, label)),
                place, str(entry.get("applyUrl") or entry.get("ref") or ""),
                entry.get("releasedDate"), "")
            if location.get("remote"):
                job.work_mode = WorkMode.REMOTE
            jobs.append(job)
        return jobs

    def _parse_personio(self, payload: Any, slug: str, label: str) -> list[Job]:
        entries = payload if isinstance(payload, list) else payload.get("jobs", [])
        jobs = []
        for entry in entries:
            description = strip_html(str(entry.get("description") or ""))
            jobs.append(self._make(
                "personio", slug, str(entry.get("id") or ""), str(entry.get("name") or ""),
                self._company_from(slug, label), str(entry.get("office") or ""),
                f"https://{slug}.jobs.personio.de/job/{entry.get('id')}",
                entry.get("createdAt"), description))
        return jobs

    # -- shared construction ----------------------------------------------

    def _make(self, provider: str, slug: str, native_id: Any, title: str, company: str,
              location: str, url: str, posted: Any, description: str) -> Job:
        scope, regions = detect_remote_scope(description)
        salary = extract_salary(description) or Salary(origin=SalaryOrigin.UNKNOWN)
        return self._job(
            provider, slug, str(native_id),
            title=title,
            company=company,
            location=location,
            work_mode=detect_work_mode(description, location),
            remote_scope=scope,
            remote_regions=regions,
            url=url,
            posted_at=parse_date(posted),
            description=description,
            language=detect_language(description),
            salary=salary,
        )
