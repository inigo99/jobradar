"""CSV export — no dependencies, opens anywhere."""

from __future__ import annotations

import csv
from pathlib import Path

from ..storage import Database

COLUMNS = [
    "id", "status", "stage", "applied_on", "score_tailored", "score_base", "company", "title",
    "location", "work_mode", "remote_scope", "posted_at", "salary_min", "salary_max",
    "salary_currency", "salary_origin", "min_years_experience", "source", "url",
    "strengths", "gaps", "alerts", "notes", "closed",
]


def rows(database: Database) -> list[dict]:
    """Flatten jobs, scores and tracking into one table."""
    scores = database.all_scores()
    applications = database.all_applications()
    result: list[dict] = []
    for job in database.list_jobs(include_closed=True):
        score = scores.get(job.id)
        application = applications.get(job.id)
        result.append(
            {
                "id": job.id,
                "status": application.status.value if application else "active",
                "stage": (application.stage.value if application and application.stage else ""),
                "applied_on": (application.applied_on.isoformat() if application and application.applied_on else ""),
                "score_tailored": score.tailored if score else "",
                "score_base": score.base if score else "",
                "company": job.company,
                "title": job.title,
                "location": job.location,
                "work_mode": job.work_mode.value,
                "remote_scope": job.remote_scope.value,
                "posted_at": job.posted_at.isoformat() if job.posted_at else "",
                "salary_min": job.salary.minimum or "",
                "salary_max": job.salary.maximum or "",
                "salary_currency": job.salary.currency,
                "salary_origin": job.salary.origin.value,
                "min_years_experience": job.min_years_experience or "",
                "source": job.source,
                "url": job.link,
                "strengths": "; ".join(score.strengths or []) if score else "",
                "gaps": "; ".join(score.gaps or []) if score else "",
                "alerts": "; ".join(job.alerts or []),
                "notes": application.notes if application else "",
                "closed": "yes" if job.closed else "",
            }
        )
    result.sort(key=lambda row: -(row["score_tailored"] or 0))
    return result


def export_csv(database: Database, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows(database))
    return path