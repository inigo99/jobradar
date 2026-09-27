"""Reading facts out of ad text without a language model."""

from datetime import date

from jobradar.models import RemoteScope, SalaryOrigin, WorkMode
from jobradar.textutils import (
    detect_language,
    detect_remote_scope,
    detect_work_mode,
    extract_min_years,
    extract_salary,
    parse_date,
    strip_html,
)


def test_hybrid_beats_remote():
    """Ads that mean hybrid nearly always also say 'remote'."""
    assert detect_work_mode("Remote friendly, hybrid: two days in the office") == WorkMode.HYBRID


def test_detects_spanish():
    text = ("Buscamos un ingeniero de datos para una empresa que valora la experiencia "
            "y el trabajo con los equipos de producto")
    assert detect_language(text) == "es"


def test_remote_scope_worldwide_and_country_lock():
    assert detect_remote_scope("You can work from anywhere in the world")[0] == RemoteScope.WORLDWIDE
    assert detect_remote_scope("Must be authorized to work in the US")[0] == RemoteScope.COUNTRY
    scope, regions = detect_remote_scope("Remote within EMEA only")
    assert scope == RemoteScope.REGION and "EMEA" in regions


def test_salary_range_and_annualisation():
    salary = extract_salary("Salario: 40.000 - 50.000 € brutos/año")
    assert salary is not None
    assert (salary.minimum, salary.maximum, salary.currency) == (40000, 50000, "EUR")
    assert salary.origin == SalaryOrigin.PUBLISHED

    monthly = extract_salary("3.000 € per month")
    assert monthly is not None
    assert monthly.minimum == 36000


def test_salary_ignores_implausible_numbers():
    assert extract_salary("Founded in 1998 with 250 employees") is None


def test_minimum_years():
    assert extract_min_years("At least 5 years of experience") == 5
    assert extract_min_years("Al menos 3 años en desarrollo") == 3
    assert extract_min_years("No experience required") is None


def test_dates():
    assert parse_date("2026-09-01") == date(2026, 9, 1)
    assert parse_date("nonsense") is None


def test_strip_html_keeps_list_structure():
    assert "• one" in strip_html("<ul><li>one</li><li>two</li></ul>")


def test_region_names_are_whole_words():
    """"Capacidad" holds "apac"; a Spanish ad is not an Asia-Pacific remote job."""
    assert detect_remote_scope("CAPACIDAD PARA ATENDER AL ALUMNADO")[0] == RemoteScope.UNKNOWN
    assert detect_remote_scope("capacitación continua")[0] == RemoteScope.UNKNOWN
    assert detect_remote_scope("Remote within APAC")[1] == ["APAC"]


def test_months_of_experience_are_not_years():
    assert extract_min_years("Experiencia mínima de 6 meses en puestos similares.") is None
    assert extract_min_years("Experiencia mínima: 2 años") == 2
    assert extract_min_years("Experiencia mínima de 1 ó 2 años en recepción") == 1


def test_titles_match_their_relatives_not_their_lookalikes():
    from jobradar.textutils import title_matches

    assert title_matches("Auxiliar de recepción", ["recepcionista"])
    assert title_matches("Fisioterapia deportiva", ["fisioterapeuta"])
    assert title_matches("Oficial de 1ª electricidad", ["electricista"])
    assert not title_matches("¿Has olvidado tu contraseña?", ["contable"])
    assert not title_matches("tecnico laboral/AUXILIAR", ["técnico de laboratorio"])
    assert not title_matches("Listado de ofertas por Comunidad Autónoma", ["técnico de comunicación"])
    assert not title_matches("Mecánico electrodomésticos", ["electricista"])
