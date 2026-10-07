"""LinkedIn through the LinkedIn MCP server: the client, the readers, the source
and the two imports. Offline: the server is replaced by a fake that answers
with what the real one returns (tests/fixtures/linkedin_mcp/)."""

from __future__ import annotations

import builtins
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobradar import linkedin_import, linkedin_mcp
from jobradar.config import Settings
from jobradar.errors import MissingDependencyError
from jobradar.linkedin_mcp import (
    LinkedInMCP,
    LinkedInMCPError,
    job_ids,
    profile_text,
    read_posting,
    titles_by_id,
    tool_result,
)
from jobradar.models import Job, WorkMode
from jobradar.pipeline.salary import ExchangeRates
from jobradar.profile import import_profile
from jobradar.sources import BY_ID, available, build_sources, resolve_enabled
from jobradar.sources.base import Fetcher, SearchQuery
from jobradar.sources.optional.linkedin_mcp import LinkedInMCPSource

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin_mcp"
TODAY = date(2026, 10, 7)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeServer:
    """Answers like the LinkedIn MCP server, and records every call."""

    def __init__(self, postings: dict[str, dict] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.closed = False
        self.postings = postings if postings is not None else {
            "4101": fixture("posting_es"),
            "4103": fixture("posting_en"),
            "4104": fixture("posting_closed"),
        }

    def call(self, tool: str, **arguments) -> dict:
        self.calls.append((tool, arguments))
        if tool == "search_jobs":
            return fixture("search")
        if tool == "get_saved_jobs":
            return fixture("saved")
        if tool == "get_my_profile":
            return fixture("profile")
        if tool == "get_job_details":
            posting = self.postings.get(arguments["job_id"])
            if posting is None:
                raise LinkedInMCPError(f"LinkedIn MCP: get_job_details failed: no job "
                                       f"{arguments['job_id']}")
            return posting
        raise AssertionError(tool)

    def reads(self) -> list[str]:
        return [arguments["job_id"] for tool, arguments in self.calls if tool == "get_job_details"]

    def close(self) -> None:
        self.closed = True


# -- reading what the server returns -------------------------------------------


def test_a_search_gives_ids_and_the_titles_it_could_read():
    result = fixture("search")
    assert job_ids(result) == ["4101", "4102", "4103", "4104"]
    assert titles_by_id(result) == {"4101": "Abogado/a junior - Derecho digital",
                                    "4102": "Mozo de almacén", "4104": "Técnico/a jurídico/a"}


def test_an_english_posting_is_read_from_its_page_text():
    posting = read_posting("4103", fixture("posting_en"), today=TODAY)
    assert posting.title == "Privacy & Data Protection Lawyer"
    assert posting.company == "Lexway Legal Tech"
    assert posting.location == "Pamplona, Navarre, Spain"
    assert posting.posted_at == TODAY - timedelta(days=3)
    assert posting.work_mode == WorkMode.HYBRID
    assert posting.state == ""
    assert posting.url == "https://www.linkedin.com/jobs/view/4103/"
    # The description, and nothing from the header or from below it.
    assert posting.description.startswith("We are looking for a junior lawyer")
    assert "English C1" in posting.description
    for noise in ("Easy Apply", "Show match details", "Set alert", "About the company",
                  "followers", "… more"):
        assert noise not in posting.description


def test_a_spanish_posting_is_read_too():
    posting = read_posting("4101", fixture("posting_es"), title="Abogado/a junior - Derecho digital",
                           today=TODAY)
    assert posting.company == "Bufete Arrieta"
    assert posting.location == "Pamplona, Comunidad Foral de Navarra, España"
    assert posting.posted_at == TODAY - timedelta(days=14)
    assert posting.work_mode == WorkMode.ONSITE
    assert posting.description == ("Despacho de Pamplona incorpora abogado/a junior para derecho "
                                   "digital y protección de datos.\n"
                                   "Se valorará formación en ciberseguridad.")


def test_a_closed_posting_says_so():
    assert read_posting("4104", fixture("posting_closed")).state == "closed"
    unmarked = fixture("posting_closed")
    del unmarked["apply"]  # the line on the page is enough
    assert read_posting("4104", unmarked).state == "closed"


def test_a_profile_becomes_a_cv_the_importer_reads():
    text = profile_text(fixture("profile"))
    lines = text.split("\n")
    assert lines[:3] == ["Pasquale Monetti", "Lawyer · Cyberlaw and data protection",
                         "Pamplona, Navarre, Spain · pasquale.monetti@example.com · "
                         "+34 600 111 222 · https://www.linkedin.com/in/pasquale-monetti/"]
    for noise in ("He/Him", "312 connections", "Open to", "Activity", "Show all"):
        assert noise not in lines
    assert "Summary\nLawyer focused on cyberlaw" in text
    assert text.index("Experience\nParalegal") < text.index("Education\n")

    # Positions, studies and languages laid out as a CV lays them out.
    assert "Paralegal — Bufete Echeverría\nPamplona, Navarra, España · 2024-09 - present" in text
    assert ("Legal Intern — Despacho Larrañaga Abogados\n"
            "Pamplona, Navarre, Spain · 2024-01 - 2024-06\n"
            "• Drafted data processing agreements") in text
    assert "Skills: RGPD" not in text
    assert ("Master's degree, Access to the Legal Profession — Universidad Pública de Navarra\n"
            "2023 - 2025") in text
    assert "Spanish (Native) · English (C1) · Italian (Native)" in text

    profile, _notes = import_profile(text)
    assert profile.contact.full_name == "Pasquale Monetti"
    assert profile.contact.email == "pasquale.monetti@example.com"
    assert profile.contact.phone == "+34 600 111 222"
    assert [(e.organization, e.start, e.end) for e in profile.experience] == [
        ("Bufete Echeverría", "2024-09", None), ("Despacho Larrañaga Abogados", "2024-01", "2024-06")]
    assert len(profile.experience[1].bullets or []) == 2
    assert [str(e.institution.get("en")) for e in profile.education] == [
        "Universidad Pública de Navarra", "Universidad de Navarra"]
    assert [(str(lang.name.get("en")), lang.level) for lang in profile.languages] == [
        ("Spanish", "Native"), ("English", "C1"), ("Italian", "Native")]


# -- the client ----------------------------------------------------------------


def test_a_tool_result_is_read_from_either_sdk_generation():
    assert tool_result("t", SimpleNamespace(is_error=False, structured_content={"a": 1},
                                            content=[])) == {"a": 1}
    assert tool_result("t", SimpleNamespace(isError=False, structuredContent={"result": {"a": 2}},
                                            content=[])) == {"a": 2}
    text_only = SimpleNamespace(is_error=False, structured_content=None,
                                content=[SimpleNamespace(text='{"job_ids": ["1"]}')])
    assert tool_result("t", text_only) == {"job_ids": ["1"]}


def test_a_tool_error_is_raised_with_a_way_out():
    failed = SimpleNamespace(is_error=True, content=[SimpleNamespace(
        text="Authentication required: no LinkedIn session, run with --login")])
    with pytest.raises(LinkedInMCPError) as caught:
        tool_result("search_jobs", failed)
    assert "Authentication required" in caught.value.message
    assert "--login" in caught.value.hint


def test_without_the_mcp_package_the_error_says_which_extra(monkeypatch):
    real_import = builtins.__import__

    def no_mcp(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mcp)
    with pytest.raises(MissingDependencyError) as caught:
        LinkedInMCP().start()
    assert "linkedin-mcp" in caught.value.hint


def test_a_missing_command_is_named():
    pytest.importorskip("mcp")
    with pytest.raises(LinkedInMCPError) as caught:
        LinkedInMCP("no-such-launcher-xyz mcp-server-linkedin").start()
    assert "no-such-launcher-xyz" in caught.value.message


def test_an_empty_command_falls_back_to_the_default():
    assert LinkedInMCP("   ").command == linkedin_mcp.DEFAULT_COMMAND


def test_a_call_waits_while_the_server_sets_up(monkeypatch):
    monkeypatch.setattr(linkedin_mcp, "SETUP_POLL", 0)
    client = LinkedInMCP(setup_wait=60)
    answers = [LinkedInMCPError("LinkedIn MCP: search_jobs failed: LinkedIn setup is not "
                                "complete yet: the server is downloading the browser."),
               {"job_ids": ["1"]}]

    def once(tool, arguments):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(client, "_call_once", once)
    assert client.call("search_jobs", keywords="x") == {"job_ids": ["1"]}


def test_other_failures_are_not_retried(monkeypatch):
    client = LinkedInMCP()
    calls = []

    def once(tool, arguments):
        calls.append(tool)
        raise LinkedInMCPError("LinkedIn MCP: search_jobs failed: rate limited")

    monkeypatch.setattr(client, "_call_once", once)
    with pytest.raises(LinkedInMCPError):
        client.call("search_jobs")
    assert calls == ["search_jobs"]


# -- the source ----------------------------------------------------------------


def source_with(server: FakeServer, tmp_path, reads: int = 25) -> LinkedInMCPSource:
    fetcher = Fetcher(Settings().sources, cache_dir=tmp_path / "cache")
    return LinkedInMCPSource(fetcher, {"client": server, "reads": reads})


def query(**overrides) -> SearchQuery:
    values = dict(titles=["abogado", "jurídico", "protección de datos", "lawyer"],
                  countries=["ES"], local_areas=["Pamplona"], local_only=True,
                  remote_wanted=False, max_age_days=7)
    values.update(overrides)
    return SearchQuery(**values)  # type: ignore[arg-type]


def test_the_source_is_restricted_and_never_on_by_default():
    assert BY_ID["linkedin_mcp"] is LinkedInMCPSource
    entry = next(s for s in available(["ES"]) if s["id"] == "linkedin_mcp")
    assert entry["tos_tier"] == "restricted" and not entry["default_enabled"]
    assert "linkedin_mcp" not in resolve_enabled(Settings().sources, ["ES"])


def test_the_source_reads_the_ads_whose_title_is_one_of_yours(tmp_path):
    server = FakeServer()
    jobs = source_with(server, tmp_path).search(query(titles=["abogado", "lawyer"]))
    # 4102 ("Mozo de almacén") is not read; 4104 is closed; 4103 had no title, so it is read.
    assert server.reads() == ["4101", "4103"]
    assert [job.native_id for job in jobs] == ["4101", "4103"]
    lawyer = jobs[1]
    assert lawyer.source == "linkedin_mcp"
    assert lawyer.company == "Lexway Legal Tech" and lawyer.work_mode == WorkMode.HYBRID
    assert lawyer.description.startswith("We are looking for")
    assert lawyer.url == "https://www.linkedin.com/jobs/view/4103/"


def test_the_search_is_asked_where_and_how_you_work(tmp_path):
    server = FakeServer()
    source_with(server, tmp_path).search(query(titles=["abogado"]))
    searches = [arguments for tool, arguments in server.calls if tool == "search_jobs"]
    assert searches == [{"keywords": "abogado", "location": "Pamplona",
                         "date_posted": "past_week", "work_type": None, "max_pages": 1}]

    server = FakeServer()
    source_with(server, tmp_path).search(query(titles=["abogado"], remote_wanted=True,
                                               max_age_days=30))
    searches = [arguments for tool, arguments in server.calls if tool == "search_jobs"]
    assert [(s["location"], s["work_type"]) for s in searches] == [("Spain", "remote"),
                                                                   ("Pamplona", None)]
    assert searches[0]["date_posted"] == "past_month"


def test_no_more_ads_are_read_than_settings_allow(tmp_path):
    server = FakeServer()
    jobs = source_with(server, tmp_path, reads=1).search(query())
    assert server.reads() == ["4101"]
    assert len(jobs) == 1


def test_an_ad_read_lately_is_not_opened_again(tmp_path):
    first = FakeServer()
    source_with(first, tmp_path).search(query())
    second = FakeServer()
    jobs = source_with(second, tmp_path, reads=1).search(query())
    assert second.reads() == []  # every reading came from the disk, and cost nothing
    assert {job.native_id for job in jobs} == {"4101", "4103"}


def test_an_unreadable_ad_is_skipped_not_fatal(tmp_path):
    server = FakeServer(postings={"4103": fixture("posting_en")})
    jobs = source_with(server, tmp_path).search(query())
    assert [job.native_id for job in jobs] == ["4103"]


def test_a_closed_ad_is_found_by_the_sweep(tmp_path):
    source = source_with(FakeServer(), tmp_path)
    closed = Job(source="linkedin_mcp", native_id="4104", title="Técnico/a jurídico/a")
    assert source.check_open(closed) == (False, "No longer accepting applications")
    assert source.check_open(Job(source="linkedin_mcp", native_id="4103", title="x"))[0] is True


def test_the_badge_settles_an_unconfirmed_work_mode(tmp_path):
    source = source_with(FakeServer(), tmp_path)
    job = source.read("4103", "")
    assert job is not None and source.resolve_work_mode(job) == WorkMode.HYBRID


def test_a_client_given_to_the_source_is_left_open(tmp_path):
    server = FakeServer()
    source_with(server, tmp_path).close()
    assert server.closed is False


def test_settings_reach_the_source(paths):
    settings = Settings(onboarded=True)
    settings.sources.enabled = ["linkedin_mcp"]
    settings.sources.linkedin_mcp_command = "uvx mcp-server-linkedin@latest"
    settings.sources.linkedin_mcp_reads = 7
    sources, fetcher = build_sources(settings, paths.cache_dir)
    try:
        (source,) = sources
        assert isinstance(source, LinkedInMCPSource)
        assert source.command == "uvx mcp-server-linkedin@latest" and source.reads == 7
    finally:
        fetcher.close()


# -- the imports ---------------------------------------------------------------


@pytest.fixture
def offline_rates(monkeypatch):
    monkeypatch.setattr(linkedin_import.ExchangeRates, "load",
                        classmethod(lambda cls, *a, **k: ExchangeRates()))


def test_saved_jobs_go_on_the_board(database, profile, offline_rates):
    database.save_settings(Settings(onboarded=True))
    database.save_profile(profile)
    server = FakeServer()
    report = linkedin_import.import_saved_jobs(database, client=server)  # type: ignore[arg-type]
    assert report.added == ["Lexway Legal Tech — Privacy & Data Protection Lawyer"]
    assert report.closed == 1 and report.unreadable == 1
    job = database.get_job(Job(source="linkedin_mcp", native_id="4103").ensure_id().id)
    assert job is not None and job.raw.get("saved_on_linkedin")
    assert database.get_score(job.id) is not None
    assert server.closed is False

    again = linkedin_import.import_saved_jobs(database, client=FakeServer())  # type: ignore[arg-type]
    assert again.added == [] and again.already_there == 1


def test_a_saved_job_you_deleted_stays_deleted(database, offline_rates):
    database.save_settings(Settings(onboarded=True))
    linkedin_import.import_saved_jobs(database, client=FakeServer())  # type: ignore[arg-type]
    job_id = Job(source="linkedin_mcp", native_id="4103").ensure_id().id
    database.delete_jobs([job_id])
    report = linkedin_import.import_saved_jobs(database, client=FakeServer())  # type: ignore[arg-type]
    assert report.added == [] and report.deleted_by_you == 1


def test_the_profile_is_imported_from_linkedin(database):
    database.save_settings(Settings(onboarded=True))
    profile, _notes = linkedin_import.import_linkedin_profile(
        database, client=FakeServer())  # type: ignore[arg-type]
    assert profile.contact.full_name == "Pasquale Monetti"
    assert profile.contact.linkedin.endswith("linkedin.com/in/pasquale-monetti/")
    stored = database.load_profile()
    assert stored is not None and stored.contact.full_name == "Pasquale Monetti"


def test_an_empty_profile_is_not_saved_over_yours(database, profile):
    database.save_settings(Settings(onboarded=True))
    database.save_profile(profile)
    empty = FakeServer()
    empty.call = lambda tool, **arguments: {"sections": {"main_profile": "Sign in"}}  # type: ignore[method-assign]
    with pytest.raises(Exception, match="almost nothing"):
        linkedin_import.import_linkedin_profile(database, client=empty)  # type: ignore[arg-type]
    stored = database.load_profile()
    assert stored is not None and stored.contact.full_name == profile.contact.full_name


# -- the dashboard and the command line ----------------------------------------


def test_the_dashboard_imports_through_the_server(paths, monkeypatch, offline_rates):
    from fastapi.testclient import TestClient

    from jobradar.web import create_app

    servers: list[FakeServer] = []

    def connect(database):
        servers.append(FakeServer())
        return servers[-1]

    monkeypatch.setattr(linkedin_import, "connect", connect)
    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as client:
        saved = client.post("/api/linkedin/saved").json()
        assert saved["ok"] and saved["added"] == [
            "Lexway Legal Tech — Privacy & Data Protection Lawyer"]
        imported = client.post("/api/linkedin/profile").json()
        assert imported["ok"] and imported["profile"]
    assert all(server.closed for server in servers)


def test_the_command_line_imports_saved_jobs(paths, monkeypatch, offline_rates, capsys):
    from jobradar.cli import main

    monkeypatch.setattr(linkedin_import, "connect", lambda database: FakeServer())
    assert main(["--home", str(paths.home), "linkedin", "saved"]) == 0
    assert "Privacy & Data Protection Lawyer" in capsys.readouterr().out
