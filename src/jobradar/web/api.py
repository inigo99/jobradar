"""Request and response models for the dashboard API.

Kept separate from the routes so the shapes the browser depends on are visible
in one place — and so that a different front end (or a script) can be written
against the same contract.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from ..config import Filters, Settings
from ..models import ApplicationStage, ApplicationStatus, CvVariant


class OnboardingPayload(BaseModel):
    """Everything the first-run wizard collects.

    The CV arrives either as an uploaded file (handled separately as multipart)
    or as pasted text in ``cv_text``; ``cv_text`` empty and no file means the
    user chose to type their details instead.
    """

    full_name: str = ""
    email: str = ""
    country: str = "ES"
    default_language: str = "en"
    cv_text: str = ""
    titles: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    filters: Filters = Field(default_factory=Filters)
    company_domains: list[str] = Field(default_factory=list)
    enabled_sources: list[str] = Field(default_factory=list)
    cv_template: str = "classic"


class SettingsPayload(BaseModel):
    """A settings update from the configuration panel."""

    settings: Settings


class ApplicationPayload(BaseModel):
    """A change to the user's own tracking record for one job."""

    status: ApplicationStatus = ApplicationStatus.ACTIVE
    stage: ApplicationStage | None = None
    applied_on: date | None = None
    notes: str = ""


class ProfilePatch(BaseModel):
    """Edits to the parts of the profile the dashboard exposes directly."""

    summary: str | None = None
    evidence: dict[str, float] | None = None
    ceiling: dict[str, float] | None = None
    #: The CV variant per job family; replaces the stored set when given.
    family_variants: dict[str, CvVariant] | None = None


class DocumentTextPayload(BaseModel):
    """The user's edited text of a cover letter or application email."""

    text: str


class JobView(BaseModel):
    """One row of the board, flattened for the browser."""

    id: str
    title: str
    company: str
    location: str
    work_mode: str
    remote_scope: str
    source: str
    url: str
    language: str
    posted_at: date | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str
    salary_origin: str
    salary_basis: str
    min_years_experience: int | None
    alerts: list[str]
    requirements: list[str]
    score_base: float
    score_tailored: float
    score_delta: float
    gaps: list[str]
    #: The same gaps with weight and learning difficulty, so the list reads as
    #: a plan for the days before an interview rather than a list of failures.
    gap_details: list[dict] = Field(default_factory=list)
    strengths: list[str]
    #: Triage order: the match score less what is already known to go nowhere.
    #: Computed fresh on every request, never stored, so it cannot go stale.
    family: str = ""
    family_label: str = ""
    focus: float = 0.0
    #: One sentence saying why this job sits where it does. A ranking nobody
    #: can audit is a ranking nobody should trust.
    focus_reason: str = ""
    status: str
    stage: str | None
    applied_on: date | None
    notes: str
    closed: bool
    has_cv: bool
    has_cover_letter: bool
    has_email: bool


class FilteredView(BaseModel):
    """One ad a filter rejected, kept so the cost of the settings is visible."""

    id: str
    company: str = ""
    title: str = ""
    source: str = ""
    url: str = ""
    posted_at: str | None = None
    reason: str = ""
    reason_shape: str = ""
    category: str = "other"
    filtered_at: str = ""
