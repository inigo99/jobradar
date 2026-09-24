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

import logging
import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from .errors import ConfigError, StorageError, describe_os_error
from .models import WorkMode

RESOURCES = Path(__file__).parent / "resources"

log = logging.getLogger(__name__)


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
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise StorageError(
                    f"Cannot create the data directory {directory}: {describe_os_error(exc)}.",
                    hint="Point --home (or JOBRADAR_HOME) at a folder you can write to.",
                ) from exc
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
    #: Discard ads demanding more than this many years of experience. Leave it
    #: unset and let ``use_profile_years`` do the work: a number typed here
    #: once is a number nobody remembers to raise, and a filter that quietly
    #: ages is worse than no filter.
    max_years_experience: int | None = None
    #: Take the ceiling from the profile's own dates instead, so it rises on
    #: its own as time passes. ``max_years_experience`` still wins if set.
    use_profile_years: bool = True
    #: Years above the candidate's own that still count as "just short". Ads in
    #: that band are separated from the ones that are far out of reach: they
    #: are worth a direct email naming the gap, even though a form would filter
    #: them out. An ad that states no years is never filtered on this at all.
    years_margin: float = 1.0
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
    #: The ``restricted`` sources (LinkedIn, InfoJobs, Tecnoempleo) fetch
    #: through a real browser via the ``scrapling`` package. Off by default,
    #: which uses Scrapling's own bundled browser — the portable choice, since
    #: it needs nothing beyond ``scrapling install``. Turn this on only on a
    #: machine you use interactively and that already has Chrome installed:
    #: it launches that Chrome instead, which is faster but is not there on a
    #: server or in CI.
    scrapling_real_chrome: bool = False


class LLMSettings(BaseModel):
    """Optional language-model configuration.

    With ``provider == "none"`` JobRadar runs entirely on deterministic rules:
    it still searches, filters, scores, renders and tracks — it just writes a
    template-based summary instead of a bespoke one, and extracts requirements
    with keyword matching instead of reading the ad.
    """

    provider: str = "none"  # none | anthropic | openai | gemini | openai-compatible | ollama
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

    #: Applications a week the user is aiming for. Drives the "Today" queue,
    #: which is the answer to "a board with two hundred jobs, now what".
    weekly_goal: int = 10
    #: How many jobs the "Today" queue shows at once. Short on purpose.
    today_queue_size: int = 6
    #: Close untouched jobs published more than this many days ago, without
    #: fetching them. The sweep only retires ads that say they are closed, and
    #: plenty of dead ones never do; checking each one costs a request (a real
    #: browser for the restricted sources). A job you applied to, discarded or
    #: annotated is never touched. ``None`` switches it off.
    prune_after_days: int | None = 45

    #: CV template used to render the tailored CV, see documents/templates.
    cv_template: str = "classic"
    #: Hard cap on CV length; the renderer shrinks type until it fits.
    cv_max_pages: int = 1

    @classmethod
    def from_yaml(cls, path: str | Path) -> Settings:
        """Load settings from a YAML file (for unattended installs)."""
        file = Path(path)
        try:
            text = file.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(
                f"The settings file {file} does not exist.",
                hint="Check the path passed to --config.",
            ) from exc
        except UnicodeDecodeError as exc:
            raise ConfigError(
                f"The settings file {file} is not UTF-8 text.",
                hint="Save it as UTF-8 and try again.",
            ) from exc
        except OSError as exc:
            raise ConfigError(
                f"Cannot read the settings file {file}: {describe_os_error(exc)}."
            ) from exc
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
            raise ConfigError(
                f"The settings file {file} is not valid YAML{where}.",
                hint="Check the indentation and quoting around that line.",
            ) from exc
        if not isinstance(data, dict):
            raise ConfigError(
                f"The settings file {file} must contain a mapping of settings, "
                f"not a {type(data).__name__}.",
                hint="See docs/CONFIGURATION.md for the expected layout.",
            )
        return cls.validated(data, origin=str(file))

    @classmethod
    def validated(cls, data: dict, origin: str = "settings") -> Settings:
        """``model_validate`` with the errors rewritten for a person to read."""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ConfigError(
                f"Invalid {origin}: {validation_summary(exc)}",
                hint="See docs/CONFIGURATION.md for the accepted values.",
            ) from exc

    def to_yaml(self, path: str | Path) -> None:
        try:
            Path(path).write_text(
                yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        except OSError as exc:
            raise ConfigError(
                f"Cannot write the settings file {path}: {describe_os_error(exc)}."
            ) from exc


def validation_summary(exc: ValidationError, limit: int = 3) -> str:
    """The first few Pydantic errors as ``field.path: message; ...``."""
    parts = []
    for error in exc.errors()[:limit]:
        location = ".".join(str(part) for part in error.get("loc", ())) or "value"
        parts.append(f"{location}: {error.get('msg', 'invalid')}")
    more = len(exc.errors()) - limit
    if more > 0:
        parts.append(f"and {more} more")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------


def load_resource(name: str) -> dict:
    """A YAML file shipped in ``resources/``, which must be a mapping.

    These files are part of the package, so a failure here means a broken
    installation rather than anything the user configured.
    """
    path = RESOURCES / name
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(
            f"The packaged resource {name} cannot be read: {describe_os_error(exc)}.",
            hint="The installation looks incomplete; reinstall JobRadar.",
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"The packaged resource {name} is not valid YAML.",
            hint="If you edited it, undo the change; otherwise reinstall JobRadar.",
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            f"The packaged resource {name} must be a mapping.",
            hint="If you edited it, undo the change; otherwise reinstall JobRadar.",
        )
    return data


@lru_cache(maxsize=1)
def countries() -> dict[str, dict]:
    """The country registry from ``resources/countries.yaml``."""
    return load_resource("countries.yaml")


@lru_cache(maxsize=1)
def salary_bands() -> dict:
    """Reference salary bands from ``resources/salary_bands.yaml``."""
    return load_resource("salary_bands.yaml")


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
    if not file.is_file():
        return
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # A broken .env must not stop the program: the variables it would
        # have set can still come from the real environment.
        log.warning("Ignoring %s: it cannot be read (%s).", file, exc)
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
