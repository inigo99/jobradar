"""Importing a CV without a language model."""

import pytest

from jobradar.profile import import_profile
from tests.conftest import SAMPLE_CV


def test_reads_contact_details():
    profile, _ = import_profile(SAMPLE_CV)
    assert profile.contact.full_name == "Alex Morgan"
    assert profile.contact.email == "alex.morgan@example.com"
    assert "linkedin.com/in/alexmorgan" in profile.contact.linkedin


def test_groups_multi_line_position_headers():
    """Title, employer and dates spread over two lines is one position."""
    profile, _ = import_profile(SAMPLE_CV)
    assert [e.organization for e in profile.experience] == ["Northwind Retail", "Cortado Analytics"]
    assert all(e.bullets for e in profile.experience)


def test_does_not_swallow_the_skills_section():
    """'Languages: Python, SQL' is a skills line, not a LANGUAGES heading."""
    profile, _ = import_profile(SAMPLE_CV)
    items = [item for group in profile.skills for item in group.items]
    assert "Python" in items and "Docker" in items


def test_reads_the_location_from_the_contact_line():
    from jobradar.models import localized

    profile, _ = import_profile(SAMPLE_CV)
    assert "Valencia" in localized(profile.contact.city, profile.default_language)


def test_evidence_distinguishes_demonstrated_from_listed():
    profile, _ = import_profile(SAMPLE_CV)
    assert profile.evidence["rest_apis"] == 1.0  # inside an achievement
    assert profile.evidence["docker"] == 0.5     # only in the skills list


def test_ceilings_never_appear_for_absent_skills():
    profile, _ = import_profile(SAMPLE_CV)
    assert "kubernetes" not in profile.ceiling


def test_years_of_experience_merges_overlaps():
    profile, _ = import_profile(SAMPLE_CV)
    assert profile.years_of_experience() > 4


SPANISH_CV = """Lucía Martín Ortega
Técnica de Recursos Humanos
lucia.martin@example.com · +34 600 000 000 · Madrid, España

EXPERIENCIA
Técnica de Recursos Humanos — Grupo Distribución Centro S.A., Madrid (03/2022 – actualidad)
- Gestión integral de nóminas de 350 empleados con A3Nom y seguros sociales.
Técnica de Selección — Adecco, Madrid (09/2019 – 02/2022)
- Reclutamiento para perfiles de logística y atención al cliente.

FORMACIÓN
Grado en Relaciones Laborales y Recursos Humanos — Universidad Complutense de Madrid (2015 – 2019)
Máster en Dirección de Recursos Humanos — ESIC (2020 – 2021)

HABILIDADES
Selección de personal, nóminas, A3Nom, formación.
"""


def test_reads_the_usual_spanish_position_line():
    from jobradar.profile.importer import heuristic_profile

    profile = heuristic_profile(SPANISH_CV)
    current, previous = profile.experience
    assert current.organization == "Grupo Distribución Centro S.A."
    assert current.location == {"es": "Madrid"}
    assert (current.start, current.end) == ("2022-03", None)
    assert previous.organization == "Adecco"
    assert (previous.start, previous.end) == ("2019-09", "2022-02")  # not "still there"
    degree, master = profile.education
    assert degree.institution == {"es": "Universidad Complutense de Madrid"}
    assert degree.degree == {"es": "Grado en Relaciones Laborales y Recursos Humanos"}
    assert master.institution == {"es": "ESIC"}
    assert profile.skills[0].items[-1] == "formación"  # no trailing full stop


@pytest.mark.parametrize("text, expected", [
    ("2021 - 2023", ("2021-01", "2023-12")),
    ("(03/2022 – actualidad)", ("2022-03", None)),
    ("marzo 2019 - febrero 2022", ("2019-03", "2022-02")),
    ("de 2015 a 2019", ("2015-01", "2019-12")),
    ("Jan 2020 – Dec 2021", ("2020-01", "2021-12")),
    ("sept. 2018 – jul. 2020", ("2018-09", "2020-07")),
    ("juillet 2017 - juin 2019", ("2017-07", "2019-06")),
    ("04.2016 bis heute", ("2016-04", None)),
    ("març 2020 - ara", ("2020-03", None)),
    ("Marketing 2019-2021", ("2019-01", "2021-12")),  # not March
])
def test_date_ranges_in_the_ways_cvs_write_them(text, expected):
    from jobradar.profile.importer import DATE_RANGE, _range

    start, end, _ongoing = _range(DATE_RANGE.search(text))
    assert (start, end) == expected
