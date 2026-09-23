"""Core data structures shared across JobRadar.

Everything here is a plain Pydantic model so that it can be serialised to JSON
(for the SQLite store and the dashboard API) and validated when it comes back
from a source adapter or a language model.

Text that a user may want in more than one language is stored as a
``LocalizedText`` mapping (``{"en": "...", "es": "..."}``) rather than a bare
string, because a tailored CV is always written in the language of the job ad.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# A mapping of ISO-639-1 language code -> text.
LocalizedText = dict[str, str]


def localized(text: LocalizedText | str | None, language: str, fallback: str = "en") -> str:
    """Return ``text`` in ``language``, falling back sensibly.

    Accepts a bare string (returned as-is) so callers do not have to care
    whether a field was localised or not.
    """
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    if language in text:
        return text[language]
    if fallback in text:
        return text[fallback]
    return next(iter(text.values()), "")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class WorkMode(str, Enum):
    """How much of the job is done from home."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class RemoteScope(str, Enum):
    """Where a remote job allows the employee to actually live.

    This is the single most common lie in job listings: a role tagged "remote"
    in London usually means "remote *within the UK*". The pipeline tries to
    resolve this per job and records the outcome here.
    """

    WORLDWIDE = "worldwide"
    REGION = "region"  # e.g. EMEA, EU, LATAM — see ``Job.remote_regions``
    COUNTRY = "country"  # remote, but only from ``Job.country``
    UNKNOWN = "unknown"


class SalaryOrigin(str, Enum):
    """Where the salary figures came from — never present an estimate as fact."""

    PUBLISHED = "published"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ApplicationStatus(str, Enum):
    """The user's own triage of a job."""

    ACTIVE = "active"  # in the pipeline, not acted on yet
    APPLIED = "applied"  # the user sent an application
    DISCARDED = "discarded"  # the user is not interested


class ApplicationStage(str, Enum):
    """How far an application got.

    ``REJECTED`` is deliberately distinct from ``ApplicationStatus.DISCARDED``:
    *discarded* means the user passed on the job, *rejected* means the company
    passed on the user. Conflating them destroys your response-rate stats.
    """

    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"


class Severity(str, Enum):
    """Severity of a linter finding."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# ---------------------------------------------------------------------------
# Profile — the single source of truth about the candidate
# ---------------------------------------------------------------------------


class Contact(BaseModel):
    """Contact block printed at the top of every generated CV."""

    full_name: str = ""
    # Some people shorten their name in English-language CVs.
    display_name: LocalizedText = Field(default_factory=dict)
    city: LocalizedText = Field(default_factory=dict)
    country: str = ""
    phone: str = ""
    email: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""

    def name_for(self, language: str) -> str:
        return localized(self.display_name, language) or self.full_name


class Bullet(BaseModel):
    """One achievement line, written once and reused across every tailored CV.

    ``text`` should follow Google's XYZ formula — *accomplished X, measured by
    Y, by doing Z*. ``skills`` lists the profile skill keys this bullet proves;
    the tailoring step uses them to decide which bullets to lead with, and the
    anti-fabrication validator uses them to decide what may be claimed at all.
    """

    id: str
    text: LocalizedText
    skills: list[str] = Field(default_factory=list)

    def has_metric(self, language: str = "en") -> bool:
        """True when the bullet contains a number, which XYZ bullets must."""
        return bool(re.search(r"\d", localized(self.text, language)))


class Experience(BaseModel):
    """A job. Positions are never reordered — only the bullets inside them."""

    id: str
    title: LocalizedText
    organization: str
    location: LocalizedText = Field(default_factory=dict)
    start: str = ""  # "YYYY-MM"
    end: str | None = None  # None == current role
    # Free text shown under the dates, e.g. two separate internship periods.
    period_note: LocalizedText = Field(default_factory=dict)
    bullets: list[Bullet] = Field(default_factory=list)


class Education(BaseModel):
    """A degree or equivalent formal qualification."""

    id: str
    degree: LocalizedText
    institution: LocalizedText
    start: str = ""
    end: str = ""
    note: LocalizedText = Field(default_factory=dict)  # thesis title, honours...


class Certification(BaseModel):
    """Short courses, vendor certificates and similar."""

    name: LocalizedText
    issuer: str = ""
    year: str = ""


class SkillGroup(BaseModel):
    """One line of the *Technical skills* block, e.g. "Languages: Python, ...".

    Groups are reordered per job family so the most relevant one comes first.
    """

    key: str
    label: LocalizedText
    items: list[str] = Field(default_factory=list)


class LanguageSkill(BaseModel):
    name: LocalizedText
    level: str = ""


class Profile(BaseModel):
    """Everything JobRadar knows about the candidate.

    This model is the *only* legitimate source of facts for a generated CV.
    ``documents.validator`` enforces that: any technology or claim that cannot
    be traced back to this object is reported as a fabrication.
    """

    schema_version: int = 1
    default_language: str = "en"
    contact: Contact = Field(default_factory=Contact)
    summary: LocalizedText = Field(default_factory=dict)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    languages: list[LanguageSkill] = Field(default_factory=list)
    extras: dict[str, LocalizedText] = Field(default_factory=dict)

    # --- The anti-fabrication model ---------------------------------------
    # ``evidence`` maps a skill key to how strongly the *base* CV proves it:
    #   1.0  demonstrated in a bullet or the summary (strong signal)
    #   0.5  merely listed under "Technical skills" (weak signal)
    #   0.0  absent — the candidate does not have it, and it can never be added
    evidence: dict[str, float] = Field(default_factory=dict)
    # ``ceiling`` caps how high a skill may be promoted in a tailored CV, i.e.
    # how strongly the candidate could defend it in an interview. A skill with
    # evidence 0.0 has no ceiling: it stays at 0.0 forever.
    ceiling: dict[str, float] = Field(default_factory=dict)
    # Human-readable label for each skill key, used in the UI and in reports.
    skill_labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("evidence", "ceiling")
    @classmethod
    def _clamp(cls, value: dict[str, float]) -> dict[str, float]:
        return {k: max(0.0, min(1.0, float(v))) for k, v in value.items()}

    # -- convenience -------------------------------------------------------

    def all_bullets(self) -> list[Bullet]:
        return [b for exp in self.experience for b in exp.bullets]

    def known_skills(self) -> set[str]:
        """Skill keys the candidate actually has (evidence above zero)."""
        return {k for k, v in self.evidence.items() if v > 0.0}

    def label_for(self, key: str) -> str:
        return self.skill_labels.get(key, key.replace("_", " "))

    def years_of_experience(self, today: date | None = None) -> float:
        """Approximate total professional experience, in years.

        Overlapping positions are merged so parallel roles are not counted
        twice. Used by the linter to sanity-check claimed seniority.
        """
        today = today or date.today()
        spans: list[tuple[date, date]] = []
        for exp in self.experience:
            start = _parse_month(exp.start)
            end = _parse_month(exp.end) if exp.end else today
            if start and end and end > start:
                spans.append((start, end))
        if not spans:
            return 0.0
        spans.sort()
        merged: list[list[date]] = [list(spans[0])]
        for start, end in spans[1:]:
            if start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        days = sum((end - start).days for start, end in merged)
        return round(days / 365.25, 1)


def _parse_month(value: str | None) -> date | None:
    """Parse ``YYYY-MM`` (or ``YYYY``) into a date, returning None on garbage."""
    if not value:
        return None
    match = re.match(r"^(\d{4})(?:-(\d{1,2}))?", value.strip())
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    try:
        return date(year, min(max(month, 1), 12), 1)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class Requirement(BaseModel):
    """One thing the job ad asks for, weighted by how much the ad insists.

    ``key`` is a profile skill key when the requirement maps onto something the
    candidate could have; otherwise it is a free key that resolves to evidence
    0.0, which is exactly how a genuine gap gets surfaced.
    """

    key: str
    label: str
    weight: int = 5

    @field_validator("weight")
    @classmethod
    def _sane_weight(cls, value: int) -> int:
        return max(1, min(10, int(value)))


class Salary(BaseModel):
    """A salary band, always annual and gross, plus where the figures came from."""

    minimum: int | None = None
    maximum: int | None = None
    currency: str = "EUR"
    origin: SalaryOrigin = SalaryOrigin.UNKNOWN
    # How the number was arrived at. Shown verbatim in the dashboard so the
    # user can tell a published band from a guess.
    basis: str = ""

    @property
    def midpoint(self) -> int | None:
        values = [v for v in (self.minimum, self.maximum) if v is not None]
        return int(sum(values) / len(values)) if values else None


class Job(BaseModel):
    """A job opening as collected from a source and enriched by the pipeline."""

    id: str = ""  # "<source>:<native_id>", filled in by ``ensure_id``
    source: str
    native_id: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    country: str = ""  # ISO-3166 alpha-2 when known
    work_mode: WorkMode = WorkMode.UNKNOWN
    remote_scope: RemoteScope = RemoteScope.UNKNOWN
    remote_regions: list[str] = Field(default_factory=list)
    url: str = ""
    apply_url: str = ""  # overrides ``url`` when the ad lives elsewhere
    posted_at: date | None = None
    description: str | None = None
    language: str = "en"
    salary: Salary | None = Field(default_factory=Salary)
    min_years_experience: int | None = None
    requirements: list[Requirement] | None = Field(default_factory=list)
    # Things the user must check before applying, e.g. "client not named".
    alerts: list[str] | None = Field(default_factory=list)
    # Source-specific payload, kept for debugging and for re-enrichment.
    raw: dict[str, Any] = Field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    closed: bool = False
    closed_reason: str = ""

    def ensure_id(self) -> Job:
        if not self.id:
            self.id = f"{self.source}:{self.native_id}"
        return self

    @property
    def link(self) -> str:
        return self.apply_url or self.url

    def fingerprint(self) -> str:
        """Stable hash of company + title, used for cross-source deduplication."""
        blob = f"{_normalise(self.company)}|{_normalise(self.title)}"
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]

    def age_days(self, today: date | None = None) -> int | None:
        if self.posted_at is None:
            return None
        return ((today or date.today()) - self.posted_at).days


def _normalise(value: str | None) -> str:
    """Lowercase, strip accents and punctuation — for fuzzy comparisons."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


class MatchScore(BaseModel):
    """How well the candidate matches a job, before and after tailoring."""

    base: float = 0.0  # score with the CV as-is
    tailored: float = 0.0  # score once relevant skills are surfaced
    delta: float = 0.0
    improvement_pct: float = 0.0
    # Requirement labels the candidate cannot meet at all, worst first.
    gaps: list[str] = Field(default_factory=list)
    # The same gaps with their weight and learning difficulty, so the list can
    # be read as a plan rather than a list of reproaches. See
    # ``taxonomy.difficulty_for``.
    gap_details: list[dict[str, Any]] = Field(default_factory=list)
    # Requirement labels the candidate meets strongly, best first.
    strengths: list[str] = Field(default_factory=list)
    # Skill keys the tailored CV should promote into bullets or the summary.
    surfaced: list[str] = Field(default_factory=list)


class Application(BaseModel):
    """The user's tracking record for one job. Never written by the pipeline."""

    job_id: str
    status: ApplicationStatus = ApplicationStatus.ACTIVE
    stage: ApplicationStage | None = None
    applied_on: date | None = None
    notes: str = ""
    updated_at: datetime | None = None


class GeneratedDocument(BaseModel):
    """A tailored artefact produced for one job."""

    job_id: str
    kind: str  # "cv" | "cover_letter" | "email"
    language: str = "en"
    text: str = ""  # plain text (letters and emails)
    path: str = ""  # file on disk (the CV PDF)
    generated_at: datetime | None = None
    # True when a language model wrote it, False for the deterministic path.
    llm_generated: bool = False


class LintFinding(BaseModel):
    """One recruiter red flag found in a generated CV."""

    rule: str
    severity: Severity
    message: str
    hint: str = ""
    location: str = ""


class SearchRun(BaseModel):
    """One execution of the search pipeline, for the run log."""

    started_at: datetime
    finished_at: datetime | None = None
    sources: list[str] = Field(default_factory=list)
    fetched: int = 0
    after_dedupe: int = 0
    kept: int = 0
    new: int = 0
    #: Already-known jobs whose stored reading was reused instead of fetching
    #: and re-reading the ad.
    reused: int = 0
    #: New ids that turned out to be a job already on file (a repost, or the
    #: same opening on another board).
    known_duplicates: int = 0
    #: Untouched jobs closed for age before the run (see ``prune_after_days``).
    pruned: int = 0
    #: Per-source counts: {"source": {"fetched": n, "kept": n}}.
    by_source: dict[str, dict[str, int]] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
