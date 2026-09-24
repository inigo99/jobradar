"""LinkedIn / InfoJobs / Tecnoempleo: each call must ask ``Fetcher`` for the
right transport.

These adapters are ``tos_tier == "restricted"`` and route every request
through ``Fetcher.get(..., browser=...)`` instead of plain HTTP (see
``sources/base.py``). What matters here is not the HTML parsing (unchanged,
and not something this migration touched) but that each call site still asks
for the browser mode it needs — losing that silently trades a working fetch
for a blocked one. A stub ``Fetcher`` records every call instead of hitting
the network or a real browser.
"""

from __future__ import annotations

from typing import Any, cast

from jobradar.sources.base import SearchQuery
from jobradar.sources.optional.infojobs import InfoJobsSource
from jobradar.sources.optional.linkedin import LinkedInGuestSource
from jobradar.sources.optional.tecnoempleo import TecnoempleoSource


class RecordingFetcher:
    """Stands in for ``Fetcher``: records every ``get`` call and answers
    from a fixed table of ``{url_prefix: body}``, matched by prefix so query
    strings don't have to be replicated here."""

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.calls: list[dict] = []

    def get(self, url, *, params=None, retries=2, use_cache=True, headers=None, browser=None,
            obey_robots=True):
        self.calls.append({"url": url, "params": params, "browser": browser,
                           "obey_robots": obey_robots})
        for prefix, body in self.responses.items():
            if url.startswith(prefix):
                return body
        return None

    def head_status(self, url):
        return None


def _query(**overrides):
    overrides.setdefault("titles", ["Data Scientist"])
    overrides.setdefault("limit", 10)
    return SearchQuery(**overrides)


# ---------------------------------------------------------------------------
# LinkedIn — every call is "dynamic"
# ---------------------------------------------------------------------------


def test_linkedin_search_uses_dynamic_browser():
    fetcher = RecordingFetcher({"https://www.linkedin.com/jobs-guest": ""})
    source = LinkedInGuestSource(cast(Any, fetcher))
    source.search(_query())
    assert fetcher.calls, "search() must call fetcher.get at least once"
    assert all(c["browser"] == "dynamic" for c in fetcher.calls)


def test_linkedin_fetch_description_uses_dynamic_browser():
    fetcher = RecordingFetcher({"https://www.linkedin.com/jobs-guest": "<html>desc</html>"})
    source = LinkedInGuestSource(cast(Any, fetcher))
    job = source.make_job("123", title="x", company="y", location="Remote")
    source.fetch_description(job)
    assert fetcher.calls[-1]["browser"] == "dynamic"


def test_linkedin_check_open_uses_dynamic_browser():
    fetcher = RecordingFetcher({"https://www.linkedin.com/jobs-guest": "still open"})
    source = LinkedInGuestSource(cast(Any, fetcher))
    job = source.make_job("123", title="x", company="y", location="Remote",
                           url="https://www.linkedin.com/jobs/view/123/")
    source.check_open(job)
    assert fetcher.calls[-1]["browser"] == "dynamic"


# ---------------------------------------------------------------------------
# InfoJobs — listing is "dynamic", the ad page is "stealthy"
# ---------------------------------------------------------------------------


def test_infojobs_search_listing_is_dynamic_and_detail_is_stealthy():
    listing = (
        '//www.infojobs.net/pamplona/data-scientist/of-iabc123 '
        'more text around it'
    )
    fetcher = RecordingFetcher({
        "https://www.infojobs.net/jobsearch": listing,
        "https://www.infojobs.net/pamplona/data-scientist/of-iabc123": "<html>ad body</html>",
    })
    source = InfoJobsSource(cast(Any, fetcher))
    source.search(_query(titles=["data scientist"]))

    listing_calls = [c for c in fetcher.calls if "jobsearch" in c["url"]]
    detail_calls = [c for c in fetcher.calls if "of-iabc123" in c["url"]]
    assert listing_calls and all(c["browser"] == "dynamic" for c in listing_calls)
    assert detail_calls and all(c["browser"] == "stealthy" for c in detail_calls)


def test_infojobs_check_open_uses_stealthy_browser():
    fetcher = RecordingFetcher({"https://www.infojobs.net/x/y/of-iabc": "still open"})
    source = InfoJobsSource(cast(Any, fetcher))
    job = source.make_job("abc", title="x", company="y", location="Pamplona",
                           url="https://www.infojobs.net/x/y/of-iabc")
    source.check_open(job)
    assert fetcher.calls[-1]["browser"] == "stealthy"


# ---------------------------------------------------------------------------
# Tecnoempleo — every call is "dynamic" (no verified need for stealth yet)
# ---------------------------------------------------------------------------


def test_tecnoempleo_search_uses_dynamic_browser():
    card = (
        'href="https://www.tecnoempleo.com/data-scientist/rf-abc123.html">'
        'Data Scientist</a>' + "x" * 20
    )
    fetcher = RecordingFetcher({
        "https://www.tecnoempleo.com/ofertas-trabajo/": card,
        "https://www.tecnoempleo.com/data-scientist/rf-abc123.html": "<html>ad</html>",
    })
    source = TecnoempleoSource(cast(Any, fetcher))
    source.search(_query(titles=["data scientist"]))
    assert fetcher.calls, "search() must call fetcher.get at least once"
    assert all(c["browser"] == "dynamic" for c in fetcher.calls)


def test_tecnoempleo_check_open_uses_dynamic_browser():
    fetcher = RecordingFetcher({"https://www.tecnoempleo.com/x.html": "still open"})
    source = TecnoempleoSource(cast(Any, fetcher))
    job = source.make_job("abc", title="x", company="y", location="Madrid",
                           url="https://www.tecnoempleo.com/x.html")
    source.check_open(job)
    assert fetcher.calls[-1]["browser"] == "dynamic"


# ---------------------------------------------------------------------------
# LinkedIn — parsing, paging and the work-mode badge
# ---------------------------------------------------------------------------

#: Two cards as the guest endpoint returns them: one company with a page (a
#: link), one without (plain text).
LINKEDIN_CARDS = """
<li><div class="base-card relative w-full base-search-card--link job-search-card"
    data-entity-urn="urn:li:jobPosting:4101" data-reference-id="x">
  <h3 class="base-search-card__title">
            Care Assistant
          </h3>
  <h4 class="base-search-card__subtitle">
    <a class="hidden-nested-link" href="https://es.linkedin.com/company/x">
            Sunrise Homes
          </a>
  </h4>
  <span class="job-search-card__location">
            Pamplona, Navarre, Spain
          </span>
  <time class="job-search-card__listdate" datetime="2026-09-22">2 days ago</time>
</div></li>
<li><div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:4102">
  <h3 class="base-search-card__title">Warehouse Operative</h3>
  <h4 class="base-search-card__subtitle">
            Local Logistics SL
          </h4>
  <span class="job-search-card__location">Tudela, Spain</span>
</div></li>
"""


def test_linkedin_parses_cards_with_and_without_a_company_link():
    source = LinkedInGuestSource(cast(Any, RecordingFetcher({})))
    jobs = source._parse_cards(LINKEDIN_CARDS)
    assert [(j.native_id, j.title, j.company) for j in jobs] == [
        ("4101", "Care Assistant", "Sunrise Homes"),
        ("4102", "Warehouse Operative", "Local Logistics SL"),
    ]
    assert jobs[0].location == "Pamplona, Navarre, Spain"
    assert str(jobs[0].posted_at) == "2026-09-22"


def test_linkedin_pages_ten_cards_at_a_time():
    fetcher = RecordingFetcher({"https://www.linkedin.com/jobs-guest/jobs/api/seeMore": LINKEDIN_CARDS})
    LinkedInGuestSource(cast(Any, fetcher)).search(_query(limit=40))
    starts = [c["params"]["start"] for c in fetcher.calls if c["params"]]
    assert starts[:3] == [0, 10, 20]


def test_restricted_sources_skip_robots_txt():
    fetcher = RecordingFetcher({"https://www.linkedin.com/jobs-guest": ""})
    LinkedInGuestSource(cast(Any, fetcher)).search(_query())
    assert fetcher.calls and all(c["obey_robots"] is False for c in fetcher.calls)


def test_linkedin_badge_settles_an_unconfirmed_remote():
    from jobradar.models import WorkMode

    page = '<div class="top-card"><span class="ui-label">Hybrid</span></div>'
    fetcher = RecordingFetcher({"https://www.linkedin.com/jobs/view/": page})
    source = LinkedInGuestSource(cast(Any, fetcher))
    job = source._parse_cards(LINKEDIN_CARDS)[0]
    assert source.resolve_work_mode(job) == WorkMode.HYBRID
    # "Similar jobs" further down the page must not be read as this ad's badge.
    far = "x" * 70_000 + ">Remote<"
    fetcher.responses = {"https://www.linkedin.com/jobs/view/": far}
    assert source.resolve_work_mode(job) is None


# ---------------------------------------------------------------------------
# Manfred and Indeed
# ---------------------------------------------------------------------------


def test_manfred_reads_structured_fields():
    from datetime import date

    from jobradar.models import SalaryOrigin, WorkMode
    from jobradar.sources.manfred import ManfredSource

    listing = [{
        "id": 7501, "slug": "enfermera-7501", "position": "Enfermera de quirófano",
        "company": {"name": "Clínica Norte"}, "locations": ["Vigo, España"],
        "remotePercentage": 0, "salaryFrom": 30000, "salaryTo": 36000,
        "updatedAt": "2026-09-22T10:00:00Z",
    }, {"id": 7502, "slug": "otra", "position": "Contable", "remotePercentage": 100}]
    detail = {
        "whatTheyAskFor": "<p>Experiencia en quirófano</p>",
        "responsibilities": ["Preparar el material", "Asistir al equipo"],
        "techs": [{"name": "Excel", "section": "COULD", "level": "BASIC"},
                  {"name": "Soporte vital avanzado", "section": "MUST", "level": "ADVANCED"}],
        "languages": [{"name": "Gallego", "level": "B2"}],
    }

    class JsonFetcher:
        def get_json(self, url, **kwargs):
            return detail if url.endswith("/7501") else listing

    source = ManfredSource(cast(Any, JsonFetcher()))
    jobs = source.search(_query(titles=["enfermera"]))
    assert [j.native_id for j in jobs] == ["7501"]
    job = jobs[0]
    assert job.company == "Clínica Norte" and job.location == "Vigo, España"
    assert job.work_mode == WorkMode.ONSITE
    assert (job.salary.minimum, job.salary.maximum, job.salary.origin) == (
        30000, 36000, SalaryOrigin.PUBLISHED)
    assert job.posted_at == date(2026, 9, 22)

    text = source.fetch_description(job)
    assert "Preparar el material" in text and "quirófano" in text
    # A MUST/ADVANCED technique is the heaviest requirement, mapped onto the
    # skill it names as a whole; an unknown name would keep its own wording.
    assert (job.requirements[0].key, job.requirements[0].weight) == ("first_aid", 10)
    assert job.requirements[1].key == "excel"
    assert job.raw["structured_requirements"] is True


def test_manfred_remote_percentage():
    from jobradar.models import WorkMode
    from jobradar.sources.manfred import work_mode_from

    assert [work_mode_from(v) for v in (100, 40, 0, None)] == [
        WorkMode.REMOTE, WorkMode.HYBRID, WorkMode.ONSITE, WorkMode.UNKNOWN]


INDEED_PAGE = """<html><script>
window.mosaic.providerData["mosaic-provider-jobcards"]={"metaData":{"mosaicProviderJobCardsModel":{"results":[
{"jobkey":"a1b2c3d4e5f6","title":"Chef de partie","company":"Hotel Mar","formattedLocation":"Remoto en Madrid",
 "pubDate":1790000000000,"snippet":"<li>Cocina mediterránea</li>",
 "extractedSalary":{"min":1800,"max":2100,"type":"MONTHLY"}}]}}};
</script></html>"""


def test_indeed_reads_the_embedded_results_and_uses_the_stealthy_browser():
    from jobradar.models import WorkMode
    from jobradar.sources.optional.indeed import IndeedSource

    fetcher = RecordingFetcher({"https://es.indeed.com/jobs": INDEED_PAGE})
    jobs = IndeedSource(cast(Any, fetcher)).search(_query(titles=["chef"], countries=["ES"]))
    assert fetcher.calls and all(c["browser"] == "stealthy" for c in fetcher.calls)
    job = jobs[0]
    assert (job.native_id, job.title, job.company) == ("a1b2c3d4e5f6", "Chef de partie", "Hotel Mar")
    assert job.url == "https://es.indeed.com/viewjob?jk=a1b2c3d4e5f6"
    assert job.work_mode == WorkMode.REMOTE
    assert (job.salary.minimum, job.salary.maximum) == (1800 * 12, 2100 * 12)
    assert job.posted_at is not None


def test_indeed_falls_back_to_html_cards():
    from jobradar.sources.optional.indeed import cards_from_html

    html = ('<a data-jk="0123456789ab"><h2 class="jobTitle"><span title="Nurse">Nurse</span></h2>'
            '<span data-testid="company-name">City Hospital</span>'
            '<div data-testid="text-location">Leeds</div></a>')
    assert cards_from_html(html) == [{"jobkey": "0123456789ab", "title": "Nurse",
                                      "company": "City Hospital", "formattedLocation": "Leeds"}]


def test_weekly_sources_only_run_on_their_day():
    from datetime import date

    from jobradar.config import SourceSettings
    from jobradar.sources import runs_today

    settings = SourceSettings(weekly=["remoteok"], weekly_day=0)
    monday, tuesday = date(2026, 9, 21), date(2026, 9, 22)
    assert runs_today("remoteok", settings, monday)
    assert not runs_today("remoteok", settings, tuesday)
    assert runs_today("himalayas", settings, tuesday)
