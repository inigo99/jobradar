"""User settings, filters and filesystem layout.

Two distinct things live here:

*Paths* — where JobRadar keeps its database, cache and generated files. These
come from the environment (``JOBRADAR_HOME``) or default to ``./data`` next to
where you run the command, so a checkout is self-contained.

*Settings* — everything the user configures: who they are, what they are
looking for, the filters applied to every job, which sources are enabled and
which language model (if any) to call. Settings are persisted in SQLite so the
dashboard and the command line always read the same values; a YAML file can be
imported at ``jobradar init`` time for unattended installs.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import WorkMode

RESOURCES = Path(__file__).parent / "resources"


# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------


class Paths(BaseModel):
    """Where everything lives on disk.

    Nothing outside ``home`` is ever written, and ``home`` is git-ignored by
    default, so personal data never ends up in a commit.
    """

    home: Path

    @classmethod
    def resolve(cls, home: str | Path | None = None) -> Paths:
        raw = home or os.environ.get("JOBRADAR_HOME") or "data"
        return cls(home=Path(raw).expanduser().resolve())

    @property
    def db(self) -> Path:
        return self.home / "jobradar.sqlite3"

    @property
    def cv_dir(self) -> Path:
        return self.home / "cv"

    @property
    def documents_dir(self) -> Path:
        return self.home / "documents"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def uploads_dir(self) -> Path:
        """Original CV files the user uploaded during onboarding."""
        return self.home / "uploads"

    def ensure(self) -> Paths:
        """Create every directory JobRadar writes to."""
        for directory in (
            self.home,
            self.cv_dir,
            self.documents_dir,
            self.cache_dir,
            self.exports_dir,
            self.uploads_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class Filters(BaseModel):
    """The rules every collected job is measured against.

    Anything left at its default is simply not applied, so a fresh install is
    permissive and the user tightens it from the dashboard.
    """

    # --- Where the work happens ------------------------------------------
    work_modes: list[WorkMode] = Field(
        default_factory=lambda: [WorkMode.REMOTE, WorkMode.HYBRID, WorkMode.ONSITE],
        description="Acceptable work modes. Drop 'onsite' to go remote-only.",
    )
    #: Areas (free text, matched case-insensitively against the job location)
    #: where hybrid and on-site roles are acceptable even if the global
    #: ``work_modes`` list is remote-only. This is how "remote anywhere, but
    #: I'd also take an office job in my own city" is expressed.
    local_areas: list[str] = Field(default_factory=list)

    # --- Where the candidate may legally live -----------------------------
    #: ISO-3166 alpha-2 code of the country the user works from.
    home_country: str = "ES"
    #: Accept remote jobs advertised from other countries, but only when the
    #: ad's geographic restriction actually allows living in ``home_country``.
    allow_international_remote: bool = True
    #: Country codes whose *domestic* postings are acceptable (usually just
    #: ``home_country``; add more if the user holds several work permits).
    eligible_countries: list[str] = Field(default_factory=list)

    # --- Money -------------------------------------------------------------
    min_salary: int | None = None
    salary_currency: str = "EUR"
    #: Drop jobs whose salary is only an estimate rather than published.
    require_published_salary: bool = False

    # --- Requirements ------------------------------------------------------
    #: Discard ads demanding more than this many years of experience.
    max_years_experience: int | None = None
    #: A job must contain at least one of these (empty == no constraint).
    required_keywords: list[str] = Field(default_factory=list)
    #: A job containing any of these is dropped (agencies, sectors, stacks...).
    excluded_keywords: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)

    # --- Freshness ---------------------------------------------------------
    max_age_days: int = 7
    #: Keep jobs whose publication date is unknown (most aggregators omit it).
    keep_undated: bool = True

    def effective_countries(self) -> list[str]:
        countries = list(self.eligible_countries)
        if self.home_country and self.home_country not in countries:
            countries.insert(0, self.home_country)
        return countries


class SourceSettings(BaseModel):
    """Which adapters run, and how politely."""

    #: Source ids to run. Empty means "every source enabled by default".
    enabled: list[str] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)
    #: Extra company domains or ATS board slugs to crawl, e.g.
    #: ``["stripe.com", "greenhouse:airbnb", "lever:netflix"]``.
    company_domains: list[str] = Field(default_factory=list)
    #: Seconds between two requests to the same host.
    request_delay: float = 1.0
    #: How many results to pull per source per run.
    max_results_per_source: int = 100
    timeout: float = 20.0
    user_agent: str = (
        "JobRadar/1.0 (+https://github.com/your-username/jobradar) "
        "personal job-search assistant"
    )
    #: Honour ``robots.txt`` before fetching a listing page. Leave this on.
    respect_robots: bool = True
    cache_ttl_minutes: int = 60


class LLMSettings(BaseModel):
    """Optional language-model configuration.

    With ``provider == "none"`` JobRadar runs entirely on deterministic rules:
    it still searches, filters, scores, renders and tracks — it just writes a
    template-based summary instead of a bespoke one, and extracts requirements
    with keyword matching instead of reading the ad.
    """

    provider: str = "none"  # none | anthropic | openai | openai-compatible | ollama
    model: str = ""
    base_url: str = ""
    #: Cap on requests per pipeline run, so an unattended cron job cannot burn
    #: an unbounded amount of credit.
    max_calls_per_run: int = 60
    temperature: float = 0.2
    max_output_tokens: int = 1500
    #: Use the model to read each job ad (requirements, work mode, salary).
    enrich_jobs: bool = True
    #: Use the model to write the tailored headline and professional summary.
    tailor_cv: bool = True
    #: Use the model for cover letters and recruiter emails (on demand only).
    write_letters: bool = True

    @property
    def enabled(self) -> bool:
        return self.provider not in ("", "none")


class NotificationSettings(BaseModel):
    """Where to send the digest of newly found jobs."""

    email_enabled: bool = False
    telegram_enabled: bool = False
    #: Only notify about jobs scoring at least this well (0-100).
    min_score: float = 0.0


class SearchSettings(BaseModel):
    """What the user is looking for."""

    #: Target job titles, used verbatim as queries against every source.
    titles: list[str] = Field(default_factory=list)
    #: Extra free keywords ORed into the queries.
    keywords: list[str] = Field(default_factory=list)
    #: Languages the user can work in; drives the language of generated docs.
    languages: list[str] = Field(default_factory=lambda: ["en"])


class Settings(BaseModel):
    """The complete, persisted user configuration."""

    schema_version: int = 1
    #: False until the onboarding wizard has been completed.
    onboarded: bool = False
    full_name: str = ""
    email: str = ""
    #: Language of the dashboard-generated documents when the ad's language is
    #: unknown. The CV itself is always written in the language of the ad.
    default_language: str = "en"
    country: str = "ES"

    search: SearchSettings = Field(default_factory=SearchSettings)
    filters: Filters = Field(default_factory=Filters)
    sources: SourceSettings = Field(default_factory=SourceSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)

    #: CV template used to render the tailored CV, see documents/templates.
    cv_template: str = "classic"
    #: Hard cap on CV length; the renderer shrinks type until it fits.
    cv_max_pages: int = 1

    @classmethod
    def from_yaml(cls, path: str | Path) -> Settings:
        """Load settings from a YAML file (for unattended installs)."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def to_yaml(self, path: str | Path) -> None:
        Path(path).write_text(
            yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def countries() -> dict[str, dict]:
    """The country registry from ``resources/countries.yaml``."""
    return yaml.safe_load((RESOURCES / "countries.yaml").read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def salary_bands() -> dict:
    """Reference salary bands from ``resources/salary_bands.yaml``."""
    return yaml.safe_load((RESOURCES / "salary_bands.yaml").read_text(encoding="utf-8")) or {}


def country_info(code: str) -> dict:
    """Registry entry for ``code``, or a neutral default for unknown countries."""
    return countries().get((code or "").upper(), {"name": code, "currency": "EUR", "languages": ["en"]})


def currency_for(code: str) -> str:
    return country_info(code).get("currency", "EUR")


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal ``.env`` loader so the package needs no extra dependency.

    Existing environment variables always win, which keeps container and CI
    overrides working.
    """
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
