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


#: What PDF text extraction gives for a two-column-free CV: wrapped bullets
#: (the cut line keeps a trailing space), "Puesto · Empresa" headers, a
#: section heading in capitals that qualifies a known one, and one heading
#: that joins three sections.
PDF_TEXT = """ANA RUIZ
Barcelona, España  ·  ana@example.com
EXPERIENCIA
Campus Manager – Operaciones de residencia  ·  Unihabit, Barcelona may. 2025 – actualidad
• Principal punto de contacto para residentes y proveedores; coordino llegadas y salidas de estudiantes 
locales e internacionales.
• Dirijo la recepción y el control de accesos del edificio, manteniendo al día incidencias, listados de 
residentes y registros de acceso.
Recepcionista nocturna  ·  Urbany Hostels, Barcelona dic. 2022 – may. 2025
• Gestioné reservas y extranets de Booking.com y Expedia con Mews cada noche.
ACTIVIDADES JURÍDICAS Y ACADÉMICAS
• Secretaria judicial en una competición de juicios simulados, Universidad de Navarra (2022).
FORMACIÓN
Máster en Derecho Digital  ·  Universitat de Barcelona oct. 2022 – dic. 2022
CERTIFICACIONES, COMPETENCIAS E IDIOMAS
Certificaciones: Cyber Network Security · Jornada sobre IA en la UE (UOC, 2022).
Competencias: Mews y extranets de OTAs · auditoría nocturna e informes de ingresos · control de 
accesos e incidencias.
Idiomas: Italiano (nativo) · Inglés C1 (EF SET) · Español B2 (DELE).
"""


def test_reads_a_cv_as_pdf_text_comes_out():
    from jobradar.profile.importer import heuristic_profile

    profile = heuristic_profile(PDF_TEXT)
    campus, night = profile.experience  # no position made of a wrapped line
    assert campus.title == {"es": "Campus Manager – Operaciones de residencia"}
    assert campus.organization == "Unihabit" and campus.location == {"es": "Barcelona"}
    assert campus.bullets[0].text["es"].endswith("estudiantes locales e internacionales.")
    assert len(campus.bullets) == 2 and len(night.bullets) == 1
    assert profile.education[0].degree == {"es": "Máster en Derecho Digital"}
    assert profile.education[0].institution == {"es": "Universitat de Barcelona"}
    assert list(profile.extras) == ["Actividades jurídicas y académicas"]
    assert [c.name["es"] for c in profile.certifications] == [
        "Cyber Network Security", "Jornada sobre IA en la UE (UOC)"]
    assert profile.certifications[1].year == "2022"
    assert profile.skills[0].items[2] == "control de accesos e incidencias"
    assert [(lang.name["es"], lang.level) for lang in profile.languages] == [
        ("Italiano", "nativo"), ("Inglés", "C1"), ("Español", "B2")]
