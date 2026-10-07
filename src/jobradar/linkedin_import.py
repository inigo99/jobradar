"""What you keep on LinkedIn, brought into JobRadar through the LinkedIn MCP server.

Two imports, both signed in as you (see :mod:`jobradar.linkedin_mcp`):

* **Saved jobs** — the ads in LinkedIn's "Saved" tab go on the board, read
  and scored like one added by hand: you chose them, so no filter is applied.
  Ads already on the board, closed or deleted by you here are left alone.
* **Your profile** — the profile is turned into the text of a CV and read by
  the CV importer, which keeps what you edited by hand in the old profile.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .errors import ProfileError
from .linkedin_mcp import PROFILE_SECTIONS, LinkedInMCP, job_ids, profile_text, titles_by_id
from .llm import build_client
from .models import Job, Profile
from .pipeline.enrich import enrich_job
from .pipeline.salary import ExchangeRates
from .pipeline.scoring import score_job
from .profile import import_profile
from .profile.vocabulary import carry_over
from .sources.base import Fetcher
from .sources.optional.linkedin_mcp import LinkedInMCPSource
from .storage import Database

log = logging.getLogger(__name__)

#: Pages of the "Saved" tab read at most (LinkedIn shows ten ads a page).
SAVED_PAGES = 3


@dataclass
class SavedImport:
    """What an import of saved jobs did."""

    #: "Company — Title" of each job put on the board.
    added: list[str] = field(default_factory=list)
    already_there: int = 0
    deleted_by_you: int = 0
    closed: int = 0
    unreadable: int = 0

    def as_dict(self) -> dict:
        return {"added": self.added, "already_there": self.already_there,
                "deleted_by_you": self.deleted_by_you, "closed": self.closed,
                "unreadable": self.unreadable}


def connect(database: Database) -> LinkedInMCP:
    """A client for the server the settings name."""
    return LinkedInMCP(database.load_settings().sources.linkedin_mcp_command)


def import_saved_jobs(database: Database, client: LinkedInMCP | None = None) -> SavedImport:
    """Put the jobs you saved on LinkedIn on the board."""
    settings = database.load_settings()
    own = client is None
    client = client or connect(database)
    fetcher = Fetcher(settings.sources, database.paths.cache_dir)
    source = LinkedInMCPSource(fetcher, {"client": client})
    llm = build_client(settings.llm)
    report = SavedImport()
    try:
        result = client.call("get_saved_jobs", max_pages=SAVED_PAGES)
        titles = titles_by_id(result)
        deleted = database.deleted_job_ids()
        profile = database.load_profile()
        rates = ExchangeRates.load(database.paths.cache_dir)
        for native_id in job_ids(result):
            job_id = Job(source=source.id, native_id=native_id).ensure_id().id
            if job_id in deleted:
                report.deleted_by_you += 1
                continue
            if database.get_job(job_id) is not None:
                report.already_there += 1
                continue
            posting = source.posting(native_id, titles.get(native_id, ""))
            if posting is None or not posting.title:
                report.unreadable += 1
                continue
            if posting.state == "closed":
                report.closed += 1
                continue
            job = source.job_from(posting)
            job.raw["saved_on_linkedin"] = True
            enrich_job(job, settings, llm=llm, rates=rates)
            database.upsert_jobs([job])
            if profile is not None:
                database.save_score(job.id, score_job(job, profile))
            report.added.append(f"{job.company} — {job.title}" if job.company else job.title)
    finally:
        if llm:
            llm.close()
        fetcher.close()
        if own:
            client.close()
    return report


def import_linkedin_profile(database: Database,
                            client: LinkedInMCP | None = None) -> tuple[Profile, list[str]]:
    """Replace the profile with your LinkedIn profile, keeping your own edits."""
    settings = database.load_settings()
    own = client is None
    client = client or connect(database)
    try:
        result = client.call("get_my_profile", sections=PROFILE_SECTIONS)
    finally:
        if own:
            client.close()
    text = profile_text(result)
    if len(text) < 80:
        raise ProfileError("LinkedIn returned almost nothing of your profile.",
                           hint="Check you are signed in: run the server once with --login.")
    llm = build_client(settings.llm)
    try:
        profile, notes = import_profile(text, llm)
    finally:
        if llm:
            llm.close()
    url = str(result.get("url") or "")
    if "/in/" in url and not profile.contact.linkedin:
        profile.contact.linkedin = url
    previous = database.load_profile()
    if previous is not None:
        carry_over(previous, profile)
    database.save_profile(profile)
    return profile, notes
