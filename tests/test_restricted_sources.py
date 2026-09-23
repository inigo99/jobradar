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

    def get(self, url, *, params=None, retries=2, use_cache=True, headers=None, browser=None):
        self.calls.append({"url": url, "browser": browser})
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
