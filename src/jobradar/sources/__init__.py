"""Source registry.

Every adapter registers here, and everything else in JobRadar discovers sources
through :func:`available` and :func:`build_sources`. Nothing imports an adapter
module directly, which is what makes adding a board a one-file change.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from ..config import Settings, SourceSettings
from ..errors import ConfigError
from .adzuna import AdzunaSource
from .arbeitnow import ArbeitnowSource
from .arbeitsagentur import ArbeitsagenturSource
from .ats import CompanyBoardsSource
from .base import Fetcher, JobSource, SearchQuery, on_by_default
from .eures import EuresSource
from .himalayas import HimalayasSource
from .jooble import JoobleSource
from .manfred import ManfredSource
from .optional.indeed import IndeedSource
from .optional.infojobs import InfoJobsSource
from .optional.linkedin import LinkedInGuestSource
from .optional.linkedin_mcp import LinkedInMCPSource
from .optional.tecnoempleo import TecnoempleoSource
from .portals import PortalsSource
from .remoteok import RemoteOKSource
from .weworkremotely import WeWorkRemotelySource

log = logging.getLogger(__name__)

#: Every adapter shipped with JobRadar, in the order they are run.
REGISTRY: tuple[type[JobSource], ...] = (
    # tos_tier == "open": documented public APIs and feeds, on by default.
    RemoteOKSource,
    WeWorkRemotelySource,
    HimalayasSource,
    ArbeitnowSource,
    ManfredSource,
    ArbeitsagenturSource,
    EuresSource,
    CompanyBoardsSource,
    PortalsSource,
    # tos_tier == "credentials": on as soon as the user supplies a free key.
    AdzunaSource,
    JoobleSource,
    # tos_tier == "restricted": never on unless the user enables them by name.
    LinkedInGuestSource,
    LinkedInMCPSource,
    InfoJobsSource,
    TecnoempleoSource,
    IndeedSource,
)

BY_ID: dict[str, type[JobSource]] = {cls.id: cls for cls in REGISTRY}


def available(countries: Iterable[str] = ()) -> list[dict]:
    """Describe every source, for the settings screen and ``jobradar sources``.

    ``countries`` are the user's: they decide whether a national board is on
    by default.
    """
    return [
        {
            "id": cls.id,
            "name": cls.name,
            "homepage": cls.homepage,
            "tos_tier": cls.tos_tier,
            "tos_note": cls.tos_note,
            "required_env": list(cls.required_env),
            "key_url": cls.key_url,
            # Whether every credential is set — never the values themselves.
            "configured": all(os.environ.get(name) for name in cls.required_env),
            # A national board's countries: the page ticks it for users who pick one.
            "countries": list(cls.countries),
            # What resolve_enabled() runs when the user has not chosen: everything but
            # the restricted tier and other countries' national boards (a
            # credentials source without its key is skipped).
            "default_enabled": on_by_default(cls, countries),
        }
        for cls in REGISTRY
    ]


def resolve_enabled(settings: SourceSettings, countries: Iterable[str] = ()) -> list[str]:
    """Work out which source ids should run.

    An empty ``enabled`` list means "the safe defaults": every open and
    credentials source, and the national boards of the user's ``countries``.
    Restricted sources are only ever included when named explicitly, and
    being named in ``disabled`` always wins.
    """
    if settings.enabled:
        unknown = [sid for sid in settings.enabled if sid not in BY_ID]
        if unknown:
            log.warning("Ignoring unknown source id(s) in sources.enabled: %s "
                        "(see 'jobradar sources' for the valid ids).", ", ".join(unknown))
        chosen = [sid for sid in settings.enabled if sid in BY_ID]
    else:
        chosen = [cls.id for cls in REGISTRY if on_by_default(cls, countries)]
    return [sid for sid in chosen if sid not in settings.disabled]


def runs_today(source_id: str, settings: SourceSettings, today: date | None = None) -> bool:
    """False for a weekly source on any day but its own."""
    if source_id not in settings.weekly:
        return True
    return (today or date.today()).weekday() == settings.weekly_day


def build_sources(settings: Settings, cache_dir: Path | None = None,
                  today: date | None = None,
                  every_day: bool = False,
                  skipped: list[dict[str, str]] | None = None) -> tuple[list[JobSource], Fetcher]:
    """Instantiate the enabled sources and the shared HTTP client.

    Sources whose credentials are missing are skipped with a log line rather
    than an exception, so a partially configured install still produces
    results from everything else. Weekly sources are skipped on any day but
    their own (``today`` defaults to the real date) unless ``every_day`` is
    set, as the closed-ad sweep does. Pass ``skipped`` to collect each
    source that did not run and why, for the run log.
    """
    skipped = skipped if skipped is not None else []
    fetcher = Fetcher(settings.sources, cache_dir)
    sources: list[JobSource] = []
    enabled = resolve_enabled(settings.sources, settings.filters.effective_countries())
    resting = 0  # weekly sources skipped today
    for source_id in enabled:
        if not every_day and not runs_today(source_id, settings.sources, today):
            log.info("Skipping %s today: it is a weekly source.", source_id)
            skipped.append({"source": source_id, "reason": "weekly source, not its day"})
            resting += 1
            continue
        cls = BY_ID[source_id]
        options: dict = {}
        if cls is CompanyBoardsSource:
            options["company_domains"] = settings.sources.company_domains
            if not options["company_domains"]:
                continue
        if cls is PortalsSource:
            options["portals"] = settings.sources.active_portals()
            if not options["portals"]:
                continue
        if cls is LinkedInMCPSource:
            options["command"] = settings.sources.linkedin_mcp_command
            options["reads"] = settings.sources.linkedin_mcp_reads
        instance = cls(fetcher, options)
        if cls.required_env and not instance.credentials_present():
            # Asked for by name, it deserves a warning; on by default, a note.
            report = log.warning if source_id in settings.sources.enabled else log.info
            report("Skipping %s: set %s to use it.", cls.name, ", ".join(cls.required_env))
            skipped.append({"source": source_id,
                            "reason": f"missing {', '.join(cls.required_env)}"})
            continue
        sources.append(instance)
    if not sources and not resting:
        fetcher.close()
        raise ConfigError(
            "No job source can run with the current settings.",
            hint="Enable at least one source (see 'jobradar sources'), or set the API keys "
                 "the enabled ones need.",
        )
    return sources, fetcher


__all__ = [
    "REGISTRY",
    "BY_ID",
    "Fetcher",
    "JobSource",
    "SearchQuery",
    "available",
    "build_sources",
    "resolve_enabled",
]
