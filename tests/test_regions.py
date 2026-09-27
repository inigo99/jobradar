"""Regions: NUTS codes, the areas people type, and "only in my areas"."""

from datetime import date
from typing import Any, cast

from jobradar.config import Filters
from jobradar.models import WorkMode
from jobradar.pipeline.filters import apply_filters
from jobradar.regions import in_areas, location_for, region_codes
from jobradar.sources.base import SearchQuery
from jobradar.sources.eures import SEARCH, EuresSource
from tests.conftest import make_job
from tests.test_public_sources import StubFetcher, _eures_entry

TODAY = date.today()


def test_a_province_code_reads_as_its_name_and_region():
    assert location_for("ES220", "Spain") == "Navarra, Spain"
    assert location_for("ES511", "Spain") == "Barcelona, Cataluña, Spain"
    assert location_for("XX999", "Spain") == "Spain"


def test_a_town_resolves_to_its_province_and_region():
    assert region_codes(["Pamplona"], "ES") == ["ES22"]
    assert region_codes(["Iruña", "Donostia"], "ES") == ["ES22", "ES21"]
    assert region_codes(["Cataluña"], "ES") == ["ES51"]
    assert region_codes(["Pamplona"], "FR") == []
    assert in_areas("Navarra, Spain", ["Pamplona"])
    assert not in_areas("Barcelona, Cataluña, Spain", ["Pamplona"])


def test_local_only_drops_jobs_elsewhere_in_the_country():
    filters = Filters(local_areas=["Pamplona"], local_only=True)
    here = make_job(work_mode=WorkMode.ONSITE, location="Navarra, Spain")
    there = make_job(work_mode=WorkMode.UNKNOWN, location="Ourense, Galicia, Spain")
    vague = make_job(work_mode=WorkMode.UNKNOWN, location="Spain")
    remote = make_job(work_mode=WorkMode.REMOTE, location="Madrid, Spain")
    assert apply_filters(here, filters, today=TODAY).keep
    outcome = apply_filters(there, filters, today=TODAY)
    assert not outcome.keep and outcome.reason.startswith("outside your areas")
    kept = apply_filters(vague, filters, today=TODAY)
    assert kept.keep and any("names no town" in w for w in kept.warnings)
    assert apply_filters(remote, filters, today=TODAY).keep  # remote is unaffected
    # Without the switch, the rest of the country is still fine.
    assert apply_filters(there, Filters(local_areas=["Pamplona"]), today=TODAY).keep


def test_eures_searches_your_areas_first_and_names_the_province():
    entry = _eures_entry(1, "Recepcionista de hotel")
    entry["locationMap"] = {"ES": ["ES220"]}
    fetcher = StubFetcher(posts={SEARCH: {"jvs": [entry]}})
    source = EuresSource(cast(Any, fetcher))
    jobs = source.search(SearchQuery(titles=["recepcionista"], countries=["ES"],
                                     local_areas=["Pamplona"], max_age_days=30))
    assert [call[2]["locationCodes"] for call in fetcher.calls] == [["ES22"], ["es"]]
    assert jobs[0].location == "Navarra, Spain"

    fetcher.calls.clear()
    source.search(SearchQuery(titles=["recepcionista"], countries=["ES"],
                              local_areas=["Pamplona"], local_only=True, max_age_days=30))
    assert [call[2]["locationCodes"] for call in fetcher.calls] == [["ES22"]]
