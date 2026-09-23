"""Tecnoempleo (Spain, tech-only) — **opt-in, restricted.**

A focused Spanish IT board. Its listing already labels each ad "100% remoto" or
"Híbrido" next to the location, so the work-mode filter can be applied before
fetching any detail page — which makes it cheap to search compared with the
generalist boards.

Every fetch here uses ``Fetcher``'s plain headless browser
(``browser="dynamic"``), the conservative default for a `restricted` source.
Unlike LinkedIn and InfoJobs, this site has not been observed blocking that —
if it starts to, escalate to ``browser="stealthy"`` the same way
``infojobs.py`` does for its ad page.
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

SEARCH = "https://www.tecnoempleo.com/ofertas-trabajo/"
CARD = re.compile(
    r'href="(https://www\.tecnoempleo\.com/[^"]*?/(?:rf-)?([0-9a-z-]+)\.html)"[^>]*>(.*?)</a>(.{0,700})',
    re.S | re.I,
)
EXPIRED = re.compile(r"oferta no disponible|caducada|finalizada", re.I)


class TecnoempleoSource(JobSource):
    id = "tecnoempleo"
    name = "Tecnoempleo"
    homepage = "https://www.tecnoempleo.com"
    tos_tier = "restricted"
    tos_note = (
        "Tecnoempleo's terms restrict automated collection. Enabling this adapter "
        "is your decision and your responsibility; keep the volume low."
    )

    def search(self, query: SearchQuery) -> list[Job]:
        jobs: dict[str, Job] = {}
        wanted = [normalise(t) for t in query.terms()]
        for term in query.terms():
            for page in range(1, 4):
                body = self.fetcher.get(
                    SEARCH, params={"te": term, "pagina": page}, browser="dynamic"
                )
                if not body:
                    break
                found = False
                for url, native_id, title_html, tail in CARD.findall(body):
                    found = True
                    title = strip_html(title_html).strip()
                    if not title or native_id in jobs:
                        continue
                    if wanted and not any(
                        any(word in normalise(title) for word in t.split()) for t in wanted
                    ):
                        continue
                    context = strip_html(tail)
                    if query.remote_only and "100% remoto" not in context.lower():
                        continue
                    job = self._detail(native_id, url, title, context)
                    if job:
                        jobs[native_id] = job
                    if len(jobs) >= query.limit:
                        return list(jobs.values())
                if not found:
                    break
        return list(jobs.values())

    def _detail(self, native_id: str, url: str, title: str, context: str) -> Job | None:
        body = self.fetcher.get(url, browser="dynamic")
        text = strip_html(body) if body else context
        lowered = f"{context} {text}".lower()
        if "100% remoto" in lowered:
            mode = WorkMode.REMOTE
        elif "híbrido" in lowered or "hibrido" in lowered:
            mode = WorkMode.HYBRID
        else:
            mode = WorkMode.ONSITE
        company = self._company(context)
        return self.make_job(
            native_id,
            title=title,
            company=company,
            location=self._location(context),
            country="ES",
            work_mode=mode,
            url=url,
            posted_at=parse_date(self._posted(context)),
            description=text,
            language=detect_language(text) or "es",
            salary=extract_salary(text, "EUR") or Salary(),
            min_years_experience=extract_min_years(text),
        )

    @staticmethod
    def _company(context: str) -> str:
        match = re.search(r"^\s*([A-ZÁÉÍÓÚÑ][^\n|]{2,60})", context.strip())
        return match.group(1).strip() if match else ""

    @staticmethod
    def _location(context: str) -> str:
        match = re.search(r"(Madrid|Barcelona|Valencia|Sevilla|Bilbao|Zaragoza|M[áa]laga|"
                          r"Navarra|Pamplona|Gipuzkoa|San Sebasti[áa]n|A Coru[ñn]a|Murcia|"
                          r"Alicante|Valladolid|Granada|Vigo|Santander|Oviedo|Toledo)", context, re.I)
        return match.group(1) if match else "España"

    @staticmethod
    def _posted(context: str) -> str:
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", context)
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}" if match else ""

    def check_open(self, job: Job) -> tuple[bool, str]:
        body = self.fetcher.get(job.link, use_cache=False, browser="dynamic")
        if body is None:
            return False, "Offer page unreachable"
        if EXPIRED.search(strip_html(body)):
            return False, "Ad expired"
        return True, ""
