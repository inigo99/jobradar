"""Source registry.

Every adapter registers here, and everything else in JobRadar discovers sources
through :func:`available` and :func:`build_sources`. Nothing imports an adapter
module directly, which is what makes adding a board a one-file change.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, SourceSettings
from .adzuna import AdzunaSource
from .arbeitnow import ArbeitnowSource
from .ats import CompanyBoardsSource
from .base import Fetcher, JobSource, SearchQuery
from .himalayas import HimalayasSource
from .jooble import JoobleSource
from .optional.infojobs import InfoJobsSource
from .optional.linkedin import LinkedInGuestSource
from .optional.tecnoempleo import TecnoempleoSource
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
    CompanyBoardsSource,
    # tos_tier == "credentials": on as soon as the user supplies a free key.
    AdzunaSource,
    JoobleSource,
    # tos_tier == "restricted": never on unless the user enables them by name.
    LinkedInGuestSource,
    InfoJobsSource,
    TecnoempleoSource,
)

BY_ID: dict[str, type[JobSource]] = {cls.id: cls for cls in REGISTRY}


def available() -> list[dict]:
    """Describe every source, for the settings screen and ``jobradar sources``."""
    return [
        {
            "id": cls.id,
            "name": cls.name,
            "homepage": cls.homepage,
            "tos_tier": cls.tos_tier,
            "tos_note": cls.tos_note,
            "required_env": list(cls.required_env),
            "default_enabled": cls.tos_tier == "open",
        }
        for cls in REGISTRY
    ]


def resolve_enabled(settings: SourceSettings) -> list[str]:
    """Work out which source ids should run.

    An empty ``enabled`` list means "the safe defaults". Restricted sources are
    only ever included when named explicitly, and being named in ``disabled``
    always wins.
    """
    if settings.enabled:
        chosen = [sid for sid in settings.enabled if sid in BY_ID]
    else:
        chosen = [cls.id for cls in REGISTRY if cls.tos_tier != "restricted"]
    return [sid for sid in chosen if sid not in settings.disabled]


def build_sources(settings: Settings, cache_dir: Path | None = None) -> tuple[list[JobSource], Fetcher]:
    """Instantiate the enabled sources and the shared HTTP client.

    Sources whose credentials are missing are skipped with a log line rather
    than an exception, so a partially configured install still produces
    results from everything else.
    """
    fetcher = Fetcher(settings.sources, cache_dir)
    sources: list[JobSource] = []
    for source_id in resolve_enabled(settings.sources):
        cls = BY_ID[source_id]
        options: dict = {}
        if cls is CompanyBoardsSource:
            options["company_domains"] = settings.sources.company_domains
            if not options["company_domains"]:
                continue
        instance = cls(fetcher, options)
        if cls.required_env and not instance.credentials_present():
            log.info("Skipping %s: missing %s", cls.name, ", ".join(cls.required_env))
            continue
        sources.append(instance)
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
