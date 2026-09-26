"""Bundesagentur für Arbeit: what is asked, how an ad is read, and that it
stays quiet unless Germany is being searched. A stub stands in for ``Fetcher``,
so nothing touches the network."""

from __future__ import annotations

import base64
from typing import Any, cast

from jobradar.sources import BY_ID, available
from jobradar.sources.arbeitsagentur import DETAILS, SEARCH, ArbeitsagenturSource
from jobradar.sources.base import SearchQuery

SEARCH_RESPONSE = {
    "stellenangebote": [
        {
            "refnr": "10000-1184867112-S",
            "titel": "Gesundheits- und Krankenpfleger (m/w/d) Intensivstation",
            "beruf": "Gesundheits- und Krankenpfleger/in",
            "arbeitgeber": "Klinikum Beispielstadt",
            "aktuelleVeroeffentlichungsdatum": "2026-09-20",
            "eintrittsdatum": "2026-10-01",
            "arbeitsort": {"ort": "Berlin", "region": "Berlin", "land": "Deutschland"},
            "externeUrl": "https://klinikum.example/jobs/42",
        },
        {"beruf": "An ad without a reference number is skipped"},
    ]
}


class StubFetcher:
    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[dict] = []

    def get_json(self, url, *, params=None, headers=None, **_):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.responses.get(url)


def _source(responses: dict[str, Any] | None = None) -> tuple[ArbeitsagenturSource, StubFetcher]:
    fetcher = StubFetcher(responses if responses is not None else {SEARCH: SEARCH_RESPONSE})
    return ArbeitsagenturSource(cast(Any, fetcher)), fetcher


def test_registered_as_an_open_source():
    assert BY_ID["arbeitsagentur"] is ArbeitsagenturSource
    entry = next(s for s in available() if s["id"] == "arbeitsagentur")
    assert entry["default_enabled"] and entry["required_env"] == []


def test_does_nothing_unless_germany_is_searched():
    source, fetcher = _source()
    assert source.search(SearchQuery(titles=["Krankenpfleger"], countries=["ES"])) == []
    assert fetcher.calls == []


def test_search_sends_the_title_the_client_id_and_the_age():
    source, fetcher = _source()
    source.search(SearchQuery(titles=["Krankenpfleger"], countries=["de"], max_age_days=500,
                              remote_only=True))
    call = fetcher.calls[0]
    assert call["url"] == SEARCH
    assert call["headers"] == {"X-API-Key": "jobboerse-jobsuche"}
    assert call["params"]["was"] == "Krankenpfleger"
    assert call["params"]["veroeffentlichtseit"] == 100  # the API's ceiling
    assert call["params"]["arbeitszeit"] == "ho"


def test_an_ad_is_read_into_a_job():
    source, _ = _source()
    jobs = source.search(SearchQuery(titles=["Krankenpfleger", "Pflegefachkraft"],
                                     countries=["DE"]))
    assert len(jobs) == 1  # the same ad for both terms is kept once; no refnr is skipped
    job = jobs[0]
    assert job.id == "arbeitsagentur:10000-1184867112-S"
    assert job.title.startswith("Gesundheits- und Krankenpfleger")
    assert job.company == "Klinikum Beispielstadt"
    assert job.location == "Berlin, Berlin"
    assert job.country == "DE" and job.language == "de"
    assert job.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1184867112-S"
    assert job.apply_url == "https://klinikum.example/jobs/42"
    assert str(job.posted_at) == "2026-09-20"


def test_the_text_comes_from_the_details_endpoint():
    refnr = "10000-1184867112-S"
    code = base64.b64encode(refnr.encode()).decode()
    details = {"stellenangebotsBeschreibung": "<p>Wir suchen Pflegekräfte.</p>",
               "verguetung": "Entgeltgruppe P8 TVöD"}
    source, fetcher = _source({SEARCH: SEARCH_RESPONSE, DETAILS.format(code=code): details})
    job = source.search(SearchQuery(titles=["Krankenpfleger"], countries=["DE"]))[0]
    text = source.fetch_description(job)
    assert "Wir suchen Pflegekräfte." in text and "<p>" not in text
    assert "Entgeltgruppe P8 TVöD" in text
    assert fetcher.calls[-1]["headers"] == {"X-API-Key": "jobboerse-jobsuche"}


def test_a_failed_details_request_keeps_what_the_job_had():
    source, _ = _source()
    job = source.search(SearchQuery(titles=["Krankenpfleger"], countries=["DE"]))[0]
    assert source.fetch_description(job) == ""
