"""The skills the jobs on the board ask for most and the profile lacks."""

from __future__ import annotations

from jobradar.gaps import skill_gaps
from jobradar.models import Application, ApplicationStatus, MatchScore
from tests.conftest import make_job


def gap(key: str, weight: int, difficulty: str = "medium") -> dict:
    return {"key": key, "label": key.title(), "weight": weight, "difficulty": difficulty,
            "note": f"{difficulty} note"}


def board():
    jobs = [make_job(native_id=str(n), company=f"Co{n}", title=f"Job {n}") for n in range(5)]
    scores = {
        jobs[0].id: MatchScore(tailored=90, gap_details=[gap("kubernetes", 8, "medium")]),
        jobs[1].id: MatchScore(tailored=80, gap_details=[gap("kubernetes", 6), gap("go", 9)]),
        jobs[2].id: MatchScore(tailored=20, gap_details=[gap("go", 9), gap("rust", 10, "slow")]),
        jobs[3].id: MatchScore(tailored=85, gap_details=[gap("terraform", 5, "fast")]),
        jobs[4].id: MatchScore(scored=False),
    }
    return jobs, scores


def test_gaps_are_added_up_and_ranked_by_what_pays_to_close():
    jobs, scores = board()
    rows = skill_gaps(jobs, {}, scores)
    assert [row.key for row in rows] == ["kubernetes", "go", "terraform", "rust"]
    kubernetes = rows[0]
    assert kubernetes.jobs == 2 and kubernetes.weight == 7.0
    assert kubernetes.priority == round(8 * 0.9 + 6 * 0.8, 1)
    assert kubernetes.examples == ["Co0 — Job 0", "Co1 — Job 1"]
    assert rows[3].difficulty == "slow"


def test_closed_and_discarded_jobs_do_not_count():
    jobs, scores = board()
    jobs[3].closed = True
    applications = {jobs[0].id: Application(job_id=jobs[0].id,
                                            status=ApplicationStatus.DISCARDED)}
    rows = {row.key: row for row in skill_gaps(jobs, applications, scores)}
    assert "terraform" not in rows
    assert rows["kubernetes"].jobs == 1


def test_the_api_and_the_command_line_show_them(paths, database, capsys):
    from fastapi.testclient import TestClient

    from jobradar.cli import main
    from jobradar.web import create_app

    jobs, scores = board()
    database.upsert_jobs(jobs)
    for job_id, score in scores.items():
        database.save_score(job_id, score)
    database.close()

    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as client:
        gaps = client.get("/api/insights").json()["gaps"]
    assert gaps[0]["key"] == "kubernetes" and gaps[0]["jobs"] == 2

    assert main(["--home", str(paths.home), "gaps"]) == 0
    assert "Kubernetes" in capsys.readouterr().out
