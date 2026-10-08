"""After applying: the follow-up for a quiet application and the interview prep pack."""

from __future__ import annotations

from datetime import date, timedelta

from jobradar.documents.followup import (
    days_waiting,
    generate_follow_up,
    generate_interview_prep,
    interview_prep_text,
)
from jobradar.models import Application, ApplicationStage, ApplicationStatus, Requirement
from jobradar.pipeline.scoring import score_job
from tests.conftest import make_job
from tests.test_answers import ScriptedModel


def applied(days: int = 14, **overrides) -> Application:
    return Application(job_id="x", status=ApplicationStatus.APPLIED,
                       applied_on=date.today() - timedelta(days=days), **overrides)


def test_days_waiting():
    assert days_waiting(applied(12)) == 12
    assert days_waiting(None) is None and days_waiting(Application(job_id="x")) is None


def test_the_follow_up_skeleton_names_the_date_and_an_achievement_already_sent(profile, settings):
    job = make_job()
    application = applied(14)
    document = generate_follow_up(profile, job, application, [], settings)
    assert document.kind == "follow_up" and not document.llm_generated
    assert document.text.startswith("Subject: Backend Engineer")
    assert application.applied_on.isoformat() in document.text
    assert "Example Ltd" in document.text and "Alex Morgan" in document.text
    assert "47%" in document.text  # the profile's achievement, verbatim


def test_the_model_writes_it_from_what_was_sent(profile, settings):
    settings.llm.write_letters = True
    model = ScriptedModel("Subject: Backend Engineer — following up\n\nHello [name],\n\n"
                          "I applied on 2026-09-20 for the Backend Engineer role at Example Ltd "
                          "and remain interested. Could you tell me where the process stands?\n\n"
                          "Best regards,\nAlex Morgan")
    document = generate_follow_up(profile, make_job(), applied(), ["My letter text."], settings,
                                  model)  # type: ignore[arg-type]
    assert document.llm_generated
    assert "My letter text." in model.prompts[0] and "<job_ad>" in model.prompts[0]


def test_the_prep_pack_maps_requirements_to_your_achievements_and_gaps(profile):
    job = make_job(alerts=["Work mode unclear — check whether office days are expected."],
                   requirements=[Requirement(key="python", label="Python", weight=10),
                                 Requirement(key="rest_apis", label="REST APIs", weight=7),
                                 Requirement(key="kubernetes", label="Kubernetes", weight=8)])
    text = interview_prep_text(profile, job, score_job(job, profile),
                               applied(stage=ApplicationStage.INTERVIEW), "en")
    assert text.startswith("Interview prep — Backend Engineer at Example Ltd")
    assert "Stage: interview" in text
    strengths = text.split("## What you can prove")[1].split("## Gaps")[0]
    assert strengths.index("Python (10)") < strengths.index("REST APIs (7)")
    python, rest = strengths.split("- REST APIs (7)")
    assert "no achievement of yours shows it" in python
    assert "Your example: Enabled 1200 stores to sync stock" in rest and "S/T:" in rest
    gaps = text.split("## Gaps — answer them honestly")[1].split("##")[0]
    assert "Kubernetes" in gaps and "I have not worked with Kubernetes directly" in gaps
    questions = text.split("## Questions worth asking them")[1]
    assert "Work mode unclear" in questions
    assert "45,000–55,000 EUR (published)" in text


def test_the_prep_pack_in_spanish_and_with_the_model(profile, settings):
    job = make_job(language="es")
    settings.llm.write_letters = True
    model = ScriptedModel("Q: ¿Cómo has trabajado con Python?\nAnswer with: el conjunto de tests "
                          "que redujo un 47% los errores en producción.\nQ: ¿Y con Kubernetes?\n"
                          "Answer with: es una carencia; lo más cercano es Docker.")
    document = generate_interview_prep(profile, job, score_job(job, profile), applied(),
                                       settings, model)  # type: ignore[arg-type]
    assert document.kind == "interview_prep" and document.llm_generated
    assert document.text.startswith("Preparación de entrevista — Backend Engineer en Example Ltd")
    assert "## Preguntas probables (modelo de lenguaje)\nQ: ¿Cómo has trabajado con Python?" \
        in document.text


def test_the_dashboard_writes_both_for_an_applied_job(paths, database, profile, settings):
    from fastapi.testclient import TestClient

    from jobradar.web import create_app

    job = make_job()
    database.save_settings(settings)
    database.save_profile(profile)
    database.upsert_jobs([job])
    database.save_application(Application(job_id=job.id, status=ApplicationStatus.APPLIED,
                                          applied_on=date.today()))
    database.close()
    with TestClient(create_app(paths, allowed_hosts={"testserver"})) as client:
        follow = client.post(f"/api/jobs/{job.id}/documents/follow_up").json()["document"]
        assert follow["kind"] == "follow_up" and "warnings" in follow
        prep = client.post(f"/api/jobs/{job.id}/documents/interview_prep").json()["document"]
        assert prep["kind"] == "interview_prep" and "warnings" not in prep
        assert client.get(f"/api/jobs/{job.id}/documents/interview_prep/pdf").status_code == 200


def test_the_command_line_drafts_follow_ups_for_quiet_applications(paths, database, profile,
                                                                     settings, capsys):
    from jobradar.cli import main

    quiet, fresh = make_job(native_id="quiet"), make_job(native_id="fresh", company="Fresh Co")
    database.save_settings(settings)
    database.save_profile(profile)
    database.upsert_jobs([quiet, fresh])
    for job, days in ((quiet, 15), (fresh, 3)):
        database.save_application(Application(job_id=job.id, status=ApplicationStatus.APPLIED,
                                              applied_on=date.today() - timedelta(days=days)))
    database.close()
    assert main(["--home", str(paths.home), "followup"]) == 0
    printed = capsys.readouterr().out
    assert "15 days" in printed and "Fresh Co" not in printed

    assert main(["--home", str(paths.home), "prep", quiet.id]) == 0
    assert "Interview prep — Backend Engineer" in capsys.readouterr().out
