"""Servicio Navarro de Empleo – Nafar Lansare (Navarre, Spain).

The regional public employment service's own offers: hospitality, industry,
care, teaching, trades — a few hundred open at a time, most of them never
posted anywhere else. There is no API, so the page built for visitors is read;
it is public-sector information, which Spanish law (Ley 37/2007) opens to
reuse, and the site sets no robots.txt rules.

It only runs when one of your areas is in Navarre (Pamplona, Tudela, Estella…),
because every offer is on site there. Each search term goes through the
portal's own search box (an ASP.NET form post), and the newest offers on the
first page are added when their title matches. Each ad's text is read from its
page later, only for ads that survive the filters.
"""

from __future__ import annotations

import html
import re

from ..models import Job, WorkMode
from ..textutils import extract_min_years, normalise, parse_date, strip_html, title_matches
from .base import JobSource, SearchQuery

BASE = "https://administracionelectronica.navarra.es/EmpleoIntermediacion"
LISTING = f"{BASE}/listadodeofertas"
AD_PAGE = f"{BASE}/empleo/{{id}}"
#: The search form's fields (ASP.NET control names).
SEARCH_BOX = "ctl00$MainContent$TextoBusquedaL"
SEARCH_BUTTON = "ctl00$MainContent$proBuscarListL"
ORDER = "ctl00$MainContent$verbien"
#: Words that put one of your areas in Navarre (compared without accents).
NAVARRE = ("navarra", "nafarroa", "navarre", "pamplona", "iruna", "tudela", "estella",
           "lizarra", "tafalla", "baranain", "burlada", "sanguesa", "alsasua", "altsasu",
           "ribera", "lodosa", "aoiz", "santesteban", "doneztebe", "zizur", "villava",
           "ansoain", "huarte", "noain", "cintruenigo", "corella", "peralta")

#: The portal's experience categories, as a minimum in years.
EXPERIENCE = {"sin experiencia": 0, "menos de un ano": 0, "1 a 3 anos": 1, "3 a 5 anos": 3,
              "mas de 5 anos": 5}

_OFFER = re.compile(r'class="miniresumen2"')
_OFFER_ID = re.compile(r'/EmpleoIntermediacion/empleo/(\d+)')
_TITLE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
_ICON_TEXT = re.compile(r'class="iconicos">(.*?)</span>', re.S)
_DATES = re.compile(r"(\d{2}/\d{2}/\d{4})")
_HIDDEN = re.compile(r"<input[^>]*type=[\"']hidden[\"'][^>]*>", re.I)
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def in_navarre(areas: list[str]) -> bool:
    return any(marker in normalise(area).split() or marker in normalise(area)
               for area in areas for marker in NAVARRE)


def hidden_fields(page: str) -> dict[str, str]:
    """The ASP.NET state a form post must send back (__VIEWSTATE and friends)."""
    fields: dict[str, str] = {}
    for tag in _HIDDEN.findall(page):
        attrs = dict(_ATTR.findall(tag))
        if attrs.get("name"):
            fields[attrs["name"]] = html.unescape(attrs.get("value", ""))
    return fields


def minimum_years(category: str) -> int | None:
    """"1 a 3 años de experiencia" -> 1: the portal states ranges, the filter wants the floor."""
    text = normalise(category)
    for label, years in EXPERIENCE.items():
        if text.startswith(label):
            return years
    return extract_min_years(category)


def _span(page: str, element_id: str) -> str:
    match = re.search(rf'id="MainContent_{element_id}"[^>]*>(.*?)</span>', page, re.S)
    return strip_html(match.group(1)) if match else ""


class NavarraSource(JobSource):
    id = "navarra"
    name = "Servicio Navarro de Empleo"
    homepage = LISTING
    tos_tier = "open"
    tos_note = ("Public offers of Navarre's employment service, read from its web page "
                "(public-sector information, reusable under Ley 37/2007). Runs only when "
                "one of your areas is in Navarre.")

    def search(self, query: SearchQuery) -> list[Job]:
        if "ES" not in {c.upper() for c in query.countries} or not in_navarre(query.local_areas):
            return []
        # Fresh, not cached: the search form must post back this visit's state.
        first = self.get(LISTING, use_cache=False)
        if not first:
            return []
        terms = query.terms()
        jobs: dict[str, Job] = {}
        # The newest offers, kept when the title matches.
        for job in self.parse_listing(first):
            if title_matches(job.title, terms):
                jobs.setdefault(job.native_id, job)
        # Then the portal's own search, which also looks beyond the first page.
        state = hidden_fields(first)
        if state:
            for term in terms:
                form = {**state, SEARCH_BOX: term, SEARCH_BUTTON: "Buscar", ORDER: "reciente",
                        "__EVENTTARGET": "", "__EVENTARGUMENT": ""}
                page = self.fetcher.post_form(LISTING, form)
                for job in self.parse_listing(page or ""):
                    jobs.setdefault(job.native_id, job)
                if len(jobs) >= query.limit:
                    break
        return list(jobs.values())[: query.limit]

    def parse_listing(self, page: str) -> list[Job]:
        jobs: list[Job] = []
        for block in _OFFER.split(page)[1:]:
            offer = _OFFER_ID.search(block)
            title = _TITLE.search(block)
            if not offer or not title:
                continue
            icons = [strip_html(text) for text in _ICON_TEXT.findall(block)]
            place = icons[0] if icons else ""
            dates = _DATES.findall(icons[-1]) if icons else []
            jobs.append(self.make_job(
                offer.group(1),
                title=strip_html(title.group(1)),
                company="Servicio Navarro de Empleo",
                location=f"{place}, Navarra" if place else "Navarra",
                country="ES",
                work_mode=WorkMode.ONSITE,
                url=AD_PAGE.format(id=offer.group(1)),
                posted_at=parse_date(dates[0]) if dates else None,
                language="es",
                raw={"closes": dates[1] if len(dates) > 1 else ""},
            ))
        return jobs

    def fetch_description(self, job: Job) -> str:
        """The ad page: duties, then the requirements and conditions as labelled lines."""
        page = self.get(job.link)
        if not page:
            return job.description or ""
        details = [
            ("Categoría profesional", _span(page, "tocupri")),
            ("Experiencia", _span(page, "lexpminima")),
            ("Estudios", _span(page, "lTitulaciones1")),
            ("Idiomas", _span(page, "LIdiomas")),
            ("Permiso de conducir", _span(page, "lcarnet")),
            ("Contrato", _span(page, "lTipoContrato")),
            ("Jornada", _span(page, "Jlaboral")),
            ("Horario", _span(page, "lhorario")),
            ("Salario", _span(page, "lSalario")),
        ]
        lines = [_span(page, "Descripcion")]
        lines += [f"{label}: {value}" for label, value in details if value]
        text = "\n".join(line for line in lines if line)
        if job.min_years_experience is None:
            job.min_years_experience = minimum_years(_span(page, "lexpminima"))
        return text or job.description or ""
