"""The taxonomy reads ads from every sector, not only software."""

from __future__ import annotations

import pytest

from jobradar.taxonomy import find_skills, taxonomy


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Enfermera/o para la UCI con experiencia en canalización de vías y triaje.",
         {"critical_care", "venepuncture", "triage"}),
        ("Registered nurse for A&E; NMC registration and wound care experience required.",
         {"nursing", "emergency_care", "professional_registration", "wound_care"}),
        ("Abogado colegiado ejerciente para litigación civil y derecho de familia.",
         {"bar_admission", "litigation", "civil_law", "family_law"}),
        ("Associate for M&A and due diligence; research on Westlaw.",
         {"corporate_law", "legal_research"}),
        ("Profesora de secundaria con habilitación lingüística (AICLE) y máster del profesorado.",
         {"secondary_teaching", "bilingual_teaching", "teaching_certificate"}),
        ("TEFL teacher, private tutoring and exam marking.",
         {"language_teaching", "tutoring", "student_assessment"}),
        ("Auxiliar de ayuda a domicilio con certificado de atención sociosanitaria.",
         {"home_care", "sociosanitary_certificate"}),
        ("Camarera de pisos y barista para hotel; se valora Opera PMS.",
         {"housekeeping", "barista", "hotel_pms"}),
        ("Jefe de obra con BIM y mediciones y presupuestos en Presto.",
         {"site_management", "bim", "surveying"}),
        ("Técnico de laboratorio: PCR, cultivo celular y normas GMP.",
         {"lab_techniques", "gmp", "clinical_lab"}),
    ],
)
def test_ads_from_other_sectors_are_read(text, expected):
    assert expected <= set(find_skills(text))


@pytest.mark.parametrize(
    "text",
    [
        "We offer private health insurance and a sustainability-minded culture.",
        "Empresa comprometida con la contratación de personas con certificado de discapacidad.",
        "You will triage bugs and own the delta lake pipelines.",
        "Contacta con Elisa en recursos humanos. Trabajamos en entornos seguros.",
        "Interpretación de datos y control de accesos en la red corporativa.",
    ],
)
def test_benefits_and_everyday_words_are_not_skills(text):
    found = set(find_skills(text))
    assert not found & {"insurance", "environmental_management", "disability_support", "triage",
                        "language_teaching", "lab_techniques", "translation", "security_guarding"}


def test_accents_are_optional():
    assert "patient_care" in find_skills("atencion al paciente")
    assert "pharmacology" in find_skills("farmacologia clinica")


def test_every_sector_has_a_real_vocabulary():
    groups: dict[str, int] = {}
    for skill in taxonomy().values():
        groups[skill.group] = groups.get(skill.group, 0) + 1
    for group in ("healthcare", "legal", "education", "care", "hospitality", "trades"):
        assert groups[group] >= 6, group


# ---------------------------------------------------------------------------
# The demo profiles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "family"), [("nurse", "healthcare"), ("lawyer", "legal"),
                                              ("teacher", "education"), ("data", "data_analytics")])
def test_each_demo_profile_fills_a_board_in_its_own_field(database, paths, name, family):
    from jobradar.demo import load_demo

    count, settings = load_demo(database, paths, name)
    jobs = database.list_jobs()
    assert count == len(jobs) >= 7
    assert sum(job.family == family for job in jobs) >= count // 2
    profile = database.load_profile()
    assert profile.experience and all(e.bullets for e in profile.experience)
    assert len(profile.evidence) >= 8
    scores = database.all_scores()
    assert max(score.tailored for score in scores.values()) >= 80  # the board is not empty-handed
    assert settings.search.titles


def test_an_unknown_demo_profile_says_which_exist(database, paths):
    from jobradar.demo import load_demo
    from jobradar.errors import ConfigError

    with pytest.raises(ConfigError) as caught:
        load_demo(database, paths, "astronaut")
    assert "nurse" in caught.value.hint
