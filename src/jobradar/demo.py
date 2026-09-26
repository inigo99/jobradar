"""The demo dataset.

``jobradar demo`` loads a synthetic profile and its synthetic jobs so a new
user can see a populated dashboard — and so the test suite and the screenshots
have something deterministic to work with — without touching a single job
board. There is one profile per kind of work (``DEMO_PROFILES``), and each set
of jobs is written to exercise the interesting cases on purpose: an ad asking
for more years than the profile has, an agency hiding its client, an ad with no
salary, one abroad, one outside the user's areas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Filters, Paths, SearchSettings, Settings
from .errors import ConfigError
from .families import classify, families_for
from .models import Job, WorkMode
from .pipeline.enrich import derive_alerts, extract_requirements_by_keyword
from .pipeline.salary import estimate_salary
from .pipeline.scoring import score_job
from .profile import import_profile
from .storage import Database

DEMO_DIR = Path(__file__).parent / "resources" / "demo"


@dataclass(frozen=True)
class DemoProfile:
    """One synthetic person and the jobs that make their board interesting."""

    cv: str
    jobs: str
    language: str
    titles: tuple[str, ...]
    work_modes: tuple[WorkMode, ...]
    local_areas: tuple[str, ...]
    min_salary: int
    description: str


#: The demo profiles, by name. JobRadar is for any kind of work, so the demo
#: is too: pick the one closest to your own field with ``--profile``.
DEMO_PROFILES: dict[str, DemoProfile] = {
    "data": DemoProfile(
        cv="sample_cv.txt", jobs="jobs.json", language="en",
        titles=("Machine Learning Engineer", "Backend Engineer", "Data Engineer"),
        work_modes=(WorkMode.REMOTE,), local_areas=("Valencia",), min_salary=30000,
        description="a data and software engineer in Valencia (English)",
    ),
    "nurse": DemoProfile(
        cv="nurse_cv.txt", jobs="nurse_jobs.json", language="es",
        titles=("Enfermera", "Enfermero", "Registered Nurse"),
        work_modes=(WorkMode.ONSITE, WorkMode.REMOTE), local_areas=("Bilbao", "Bizkaia"),
        min_salary=26000,
        description="an emergency and intensive-care nurse in Bilbao (Spanish)",
    ),
    "lawyer": DemoProfile(
        cv="lawyer_cv.txt", jobs="lawyer_jobs.json", language="es",
        titles=("Abogado", "Abogada", "Legal Counsel"),
        work_modes=(WorkMode.HYBRID, WorkMode.ONSITE), local_areas=("Madrid",),
        min_salary=32000,
        description="a civil-litigation and data-protection lawyer in Madrid (Spanish)",
    ),
    "teacher": DemoProfile(
        cv="teacher_cv.txt", jobs="teacher_jobs.json", language="en",
        titles=("English Teacher", "Profesor de Inglés", "Profesora de Inglés"),
        work_modes=(WorkMode.ONSITE, WorkMode.REMOTE), local_areas=("Valencia",),
        min_salary=18000,
        description="an English teacher and CLIL coordinator in Valencia (English)",
    ),
}
DEFAULT_DEMO = "data"


def load_demo(database: Database, paths: Paths | None = None,
              profile_name: str = DEFAULT_DEMO) -> tuple[int, Settings]:
    """Populate a database with a demo profile, its settings and its jobs."""
    demo = DEMO_PROFILES.get(profile_name)
    if demo is None:
        raise ConfigError(
            f"There is no demo profile called '{profile_name}'.",
            hint="Choose one of: " + ", ".join(sorted(DEMO_PROFILES)) + ".",
        )
    profile, _notes = import_profile((DEMO_DIR / demo.cv).read_text(encoding="utf-8"))
    database.save_profile(profile)

    settings = Settings(
        onboarded=True,
        full_name=profile.contact.full_name,
        email=profile.contact.email,
        country="ES",
        default_language=demo.language,
        search=SearchSettings(
            titles=list(demo.titles),
            keywords=[],
            languages=["en", "es"],
        ),
        filters=Filters(
            work_modes=list(demo.work_modes),
            local_areas=list(demo.local_areas),
            home_country="ES",
            min_salary=demo.min_salary,
            salary_currency="EUR",
            max_age_days=14,
        ),
    )
    database.save_settings(settings)

    jobs = [Job.model_validate(entry).ensure_id() for entry in
            json.loads((DEMO_DIR / demo.jobs).read_text(encoding="utf-8"))]
    families = families_for(settings)
    for job in jobs:
        job.requirements = extract_requirements_by_keyword(job)
        job.family = classify(job, families)
        if job.salary is None or not job.salary.midpoint:
            job.salary = estimate_salary(job, settings.filters.salary_currency,
                                         families=families,
                                         home_country=settings.filters.home_country)
        job.alerts = derive_alerts(job)
    database.upsert_jobs(jobs)
    for job in jobs:
        database.save_score(job.id, score_job(job, profile))
    return len(jobs), settings
