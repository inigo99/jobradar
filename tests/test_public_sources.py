"""EURES and "your portals": what is asked and how the answers are read. A stub stands in for ``Fetcher``; nothing touches
the network."""

from __future__ import annotations

from typing import Any, cast

from jobradar.config import Portal, Settings
from jobradar.sources import BY_ID, build_sources
from jobradar.sources.base import SearchQuery
from jobradar.sources.eures import SEARCH, EuresSource, publication_period
from jobradar.sources.portals import PortalsSource, feed_items, job_postings
from jobradar.textutils import title_matches


class StubFetcher:
    """Answers by URL prefix and records every call."""

    def __init__(self, pages: dict[str, Any] | None = None, posts: dict[str, Any] | None = None):
        self.pages = pages or {}
        self.posts = posts or {}
        self.calls: list[tuple[str, str, Any]] = []
        self.problems: list[str] = []

    def _answer(self, table: dict[str, Any], url: str) -> Any:
        for prefix, body in table.items():
            if url.startswith(prefix):
                return body
        return None

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs.get("params")))
        return self._answer(self.pages, url)

    def post_json(self, url, payload, headers=None):
        self.calls.append(("POST", url, payload))
        return self._answer(self.posts, url)

    def _report_once(self, key, message):
        self.problems.append(message)


def test_title_matching_survives_gender_and_accents():
    assert title_matches("Enfermero/a UCI", ["enfermera"])
    assert title_matches("Profesor/a de inglés para academia", ["profesor de ingles"])
    assert not title_matches("Técnico/a de turismo", ["enfermera"])
    assert title_matches("Anything at all", [])


def test_new_sources_are_registered_as_open():
    for source_id in ("eures", "portals"):
        assert BY_ID[source_id].tos_tier == "open"


# ---------------------------------------------------------------------------
# EURES
# ---------------------------------------------------------------------------

EURES_ANSWER = {
    "numberRecords": 2,
    "jvs": [
        {
            "id": "MTAwMDEtMTAwMTEzOTMxMS1TIDE",
            "title": "Nurse (machine translation)",
            "description": "<p>translated</p>",
            "creationDate": 1790400000000,
            "locationMap": {"ES": ["ES220"]},
            "employer": {"name": "Hospital Universitario de Navarra"},
            "availableLanguages": ["es"],
            "translations": {"es": {"title": "Enfermero/a de urgencias",
                                    "description": "<p>Se busca enfermero/a. Salario 32.000 € brutos anuales.</p>"}},
            "positionScheduleCodes": ["fulltime"],
        },
        {"title": "no id, skipped"},
    ],
}


def test_eures_asks_by_country_age_and_language():
    fetcher = StubFetcher(posts={SEARCH: EURES_ANSWER})
    jobs = EuresSource(cast(Any, fetcher)).search(
        SearchQuery(titles=["enfermera"], countries=["ES", "GR"], max_age_days=7,
                    languages=["es", "en"]))
    _, url, payload = fetcher.calls[0]
    assert url == SEARCH
    assert payload["locationCodes"] == ["es", "el"]  # Greece is "el" in NUTS
    assert payload["publicationPeriod"] == "LAST_WEEK"
    assert payload["requestLanguage"] == "es"
    assert payload["keywords"] == [{"keyword": "enfermera", "specificSearchCode": "EVERYWHERE"}]
    assert len(jobs) == 1


def test_eures_reads_the_ad_in_its_own_language():
    fetcher = StubFetcher(posts={SEARCH: EURES_ANSWER})
    job = EuresSource(cast(Any, fetcher)).search(SearchQuery(titles=["nurse"], countries=["ES"]))[0]
    assert job.title == "Enfermero/a de urgencias"
    assert "Se busca enfermero/a." in job.description and "<p>" not in job.description
    assert job.company == "Hospital Universitario de Navarra"
    assert job.country == "ES" and job.language == "es"
    assert job.url.startswith("https://europa.eu/eures/portal/jv-se/jv-details/MTAw")
    assert job.posted_at is not None and job.posted_at.year == 2026


def test_eures_skips_countries_it_does_not_cover():
    fetcher = StubFetcher(posts={SEARCH: EURES_ANSWER})
    assert EuresSource(cast(Any, fetcher)).search(SearchQuery(titles=["x"], countries=["US"])) == []
    assert fetcher.calls == []


def test_publication_period_never_narrower_than_the_filter():
    assert publication_period(1) == "LAST_DAY"
    assert publication_period(5) == "LAST_WEEK"
    assert publication_period(20) == "LAST_MONTH"
    assert publication_period(90) is None


# ---------------------------------------------------------------------------
# Your portals
# ---------------------------------------------------------------------------

FEED = '''<?xml version="1.0"?><rss><channel>
  <item><title>Enfermero/a quirófano</title><link>https://board.example/o/1</link>
        <description><![CDATA[<p>Hospital en Pamplona</p>]]></description>
        <pubDate>Fri, 25 Sep 2026 10:00:00 +0000</pubDate></item>
  <item><title>Contable</title><link>https://board.example/o/2</link></item>
</channel></rss>'''

JSON_LD_PAGE = '''<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [{"@type": "JobPosting",
  "title": "Enfermera de UCI", "url": "/ofertas/77",
  "hiringOrganization": {"@type": "Organization", "name": "Clínica San Miguel"},
  "jobLocation": {"@type": "Place", "address": {"addressLocality": "Pamplona",
                  "addressRegion": "Navarra", "addressCountry": "ES"}},
  "datePosted": "2026-09-20", "description": "<p>Turnos rotativos.</p>"},
  {"@type": "JobPosting", "title": "Soldador", "url": "/ofertas/78"}]}
</script></head><body></body></html>'''

LINKS_PAGE = '''<html><body><nav><a href="/">Inicio</a><a href="/empresas">Empresas</a></nav>
  <ul><li><a href="/oferta/5">Enfermero/a de residencia</a></li>
      <li><a href="/oferta/6">Mozo/a de almacén</a></li></ul></body></html>'''


def _portals(portals: list[str], pages: dict[str, str], titles: list[str]) -> tuple[list, StubFetcher]:
    fetcher = StubFetcher(pages=pages)
    source = PortalsSource(cast(Any, fetcher), {"portals": portals})
    return source.search(SearchQuery(titles=titles, countries=["ES"])), fetcher


def test_a_feed_gives_its_matching_items():
    assert feed_items("<html></html>") is None
    jobs, _ = _portals(["https://board.example/rss"], {"https://board.example/rss": FEED}, ["enfermera"])
    assert [job.title for job in jobs] == ["Enfermero/a quirófano"]
    assert jobs[0].url == "https://board.example/o/1" and "Hospital en Pamplona" in jobs[0].description
    assert jobs[0].company == "board.example"


def test_jobposting_markup_gives_complete_offers():
    assert len(job_postings(JSON_LD_PAGE)) == 2
    jobs, _ = _portals(["https://clinic.example/empleo"],
                       {"https://clinic.example/empleo": JSON_LD_PAGE}, ["enfermera"])
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Enfermera de UCI" and job.company == "Clínica San Miguel"
    assert job.location == "Pamplona, Navarra" and job.country == "ES"
    assert job.url == "https://clinic.example/ofertas/77"
    assert str(job.posted_at) == "2026-09-20" and job.description == "Turnos rotativos."


def test_without_markup_the_links_matching_your_titles_are_used():
    jobs, _ = _portals(["https://jobs.example/lista"], {"https://jobs.example/lista": LINKS_PAGE},
                       ["enfermera"])
    assert [(job.title, job.url) for job in jobs] == [
        ("Enfermero/a de residencia", "https://jobs.example/oferta/5")]


def test_a_search_address_is_filled_in_once_per_term():
    pages = {"https://jobs.example/buscar?q=": LINKS_PAGE}
    _, fetcher = _portals(["https://jobs.example/buscar?q={query}"], pages,
                          ["enfermera", "mozo almacén"])
    asked = [url for kind, url, _ in fetcher.calls if kind == "GET"]
    assert asked == ["https://jobs.example/buscar?q=enfermera",
                     "https://jobs.example/buscar?q=mozo+almacen"]  # accents left out


def test_an_unreadable_portal_is_reported_not_silent():
    jobs, fetcher = _portals(["https://down.example/"], {}, ["enfermera"])
    assert jobs == [] and fetcher.problems and "down.example" in fetcher.problems[0]
    _, fetcher = _portals(["https://empty.example/"], {"https://empty.example/": "<html></html>"},
                          ["enfermera"])
    assert "Nothing recognisable" in fetcher.problems[0]


def test_portals_only_run_when_some_are_listed(tmp_path):
    settings = Settings()
    sources, fetcher = build_sources(settings, tmp_path)
    assert "portals" not in {s.id for s in sources}
    fetcher.close()
    settings.sources.portals = [Portal(url="https://jobs.example/rss"),
                                Portal(url="https://paused.example/", enabled=False)]
    sources, fetcher = build_sources(settings, tmp_path)
    portals = next(s for s in sources if s.id == "portals")
    assert portals.options["portals"] == ["https://jobs.example/rss"]  # the paused one is kept
    fetcher.close()
    settings.sources.portals[0].enabled = False
    sources, fetcher = build_sources(settings, tmp_path)
    assert "portals" not in {s.id for s in sources}  # all paused: nothing to read
    fetcher.close()


def test_a_bare_address_is_read_as_a_portal():
    settings = Settings.model_validate({"sources": {"portals": ["https://a.example/?q={query}"]}})
    assert settings.sources.portals == [Portal(url="https://a.example/?q={query}")]
    assert settings.sources.active_portals() == ["https://a.example/?q={query}"]


def test_a_result_card_link_takes_its_heading_as_title():
    page = ('<li><a href="/offres/detail/214LBZJ"><div><h2><span>Infirmier en EHPAD (H/F)</span></h2>'
            '<p>LES RIVES D\'ITHAQUE - 63 - LA ROCHE BLANCHE</p><p class="description">'
            + "Dans un cadre calme et verdoyant, " * 10 + '</p></div></a></li>')
    jobs, _ = _portals(["https://ft.example/offres"], {"https://ft.example/offres": page}, ["infirmier"])
    assert [job.title for job in jobs] == ["Infirmier en EHPAD (H/F)"]


def test_session_parameters_do_not_make_the_same_ad_new_every_day():
    from jobradar.sources.portals import canonical
    first = ("https://www.sistemanacionalempleo.es/OfertaDifusionWEB/detalleOferta.do"
             "?modo=inicio&id=132026008310&ret=B&idFlujo=IQ0btG")
    again = first.replace("IQ0btG", "wBLzxI")
    assert canonical(first) == canonical(again) == (
        "https://www.sistemanacionalempleo.es/OfertaDifusionWEB/detalleOferta.do"
        "?modo=inicio&id=132026008310")
    page = f'<a href="{first}">Enfermera/o en Leganés</a>'
    jobs, _ = _portals(["https://sne.example/"], {"https://sne.example/": page}, ["enfermera"])
    assert jobs[0].url == canonical(first)
