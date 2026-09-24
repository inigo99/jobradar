"""The demo dataset.

``jobradar demo`` loads a synthetic profile and ten synthetic jobs so a new
user can see a populated dashboard — and so the test suite and the screenshots
have something deterministic to work with — without touching a single job
board. The jobs are written to exercise the interesting cases on purpose: a
US-only "remote" role, an EMEA one, an agency posting that hides its client, an
ad with no salary, and an on-site job outside the user's areas.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Filters, Paths, SearchSettings, Settings
from .families import classify, families_for
from .models import Job, WorkMode
from .pipeline.enrich import derive_alerts, extract_requirements_by_keyword
from .pipeline.salary import estimate_salary
from .pipeline.scoring import score_job
from .profile import import_profile
from .storage import Database

DEMO_DIR = Path(__file__).parent / "resources" / "demo"


def load_demo(database: Database, paths: Paths | None = None) -> tuple[int, Settings]:
    """Populate a database with the demo profile, settings and jobs."""
    profile, _notes = import_profile((DEMO_DIR / "sample_cv.txt").read_text(encoding="utf-8"))
    database.save_profile(profile)

    settings = Settings(
        onboarded=True,
        full_name=profile.contact.full_name,
        email=profile.contact.email,
        country="ES",
        default_language="en",
        search=SearchSettings(
            titles=["Machine Learning Engineer", "Backend Engineer", "Data Engineer"],
            keywords=["Python"],
            languages=["en", "es"],
        ),
        filters=Filters(
            work_modes=[WorkMode.REMOTE],
            local_areas=["Valencia"],
            home_country="ES",
            min_salary=30000,
            salary_currency="EUR",
            max_age_days=14,
        ),
    )
    database.save_settings(settings)

    jobs = [Job.model_validate(entry).ensure_id() for entry in
            json.loads((DEMO_DIR / "jobs.json").read_text(encoding="utf-8"))]
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
