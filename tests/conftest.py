"""Shared fixtures.

Every test runs against a temporary data directory, so the suite never touches
a real installation and can run in parallel.
"""

from __future__ import annotations

import pytest

from jobradar.config import Paths, Settings
from jobradar.models import Job, Requirement, Salary, SalaryOrigin, WorkMode
from jobradar.profile import import_profile
from jobradar.storage import Database

SAMPLE_CV = """ALEX MORGAN
Valencia, Spain · +34 600 000 000 · alex.morgan@example.com · linkedin.com/in/alexmorgan

PROFESSIONAL SUMMARY
Software engineer with an MSc in Data Science.

PROFESSIONAL EXPERIENCE
Backend Engineer — Northwind Retail
Valencia, Spain · 2022-03 - present
• Cut checkout errors reported in production by 47% by introducing an integration test suite.
• Enabled 1200 stores to sync stock by designing the REST APIs between the ERP and e-commerce.

Data Analyst — Cortado Analytics
Valencia, Spain · 2020-06 - 2022-02
• Cut weekly reporting effort by 12 hours by automating the ETL feeding the sales dashboards.

EDUCATION
MSc in Data Science — Polytechnic University of Valencia
2019-09 - 2020-07

TECHNICAL SKILLS
Languages: Python, SQL, JavaScript
Infrastructure: Docker, AWS, PostgreSQL, FastAPI

LANGUAGES
Spanish (Native) · English (C1)
"""


@pytest.fixture
def paths(tmp_path):
    return Paths(home=tmp_path / "data").ensure()


@pytest.fixture
def database(paths):
    db = Database(paths)
    yield db
    db.close()


@pytest.fixture
def profile():
    imported, _notes = import_profile(SAMPLE_CV)
    return imported


@pytest.fixture
def settings():
    return Settings(onboarded=True, full_name="Alex Morgan", country="ES")


def make_job(**overrides) -> Job:
    """A plausible job, with everything the filters look at already set."""
    defaults = dict(
        source="test",
        native_id="1",
        title="Backend Engineer",
        company="Example Ltd",
        location="Remote — Spain",
        country="ES",
        work_mode=WorkMode.REMOTE,
        language="en",
        description="Python, Docker and REST APIs.",
        salary=Salary(minimum=45000, maximum=55000, currency="EUR",
                      origin=SalaryOrigin.PUBLISHED, basis="Published."),
        requirements=[
            Requirement(key="python", label="Python", weight=10),
            Requirement(key="docker", label="Docker", weight=6),
            Requirement(key="kubernetes", label="Kubernetes", weight=8),
        ],
    )
    defaults.update(overrides)
    return Job(**defaults).ensure_id()
