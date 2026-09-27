"""The taxonomy has to be precise, because everything downstream trusts it."""

from jobradar.taxonomy import find_skills, label_for


def test_finds_plain_skills():
    found = find_skills("We use Python, Docker and Kubernetes in production.")
    assert {"python", "docker", "kubernetes"} <= set(found)


def test_matches_plurals():
    assert "rest_apis" in find_skills("You will design REST APIs for our partners.")


def test_does_not_match_inside_other_words():
    """The failure mode this guards against is real: 'Alan' inside 'Talan'."""
    found = find_skills("We are Talan, a Braintrust partner, and we love Javascripting.")
    assert "java" not in found
    assert "rust" not in found


def test_java_is_not_javascript():
    assert set(find_skills("JavaScript developer")) == {"javascript"}


def test_label_falls_back_for_unknown_keys():
    assert label_for("some_new_thing") == "Some New Thing"


def test_hospitality_and_language_vocabulary():
    found = find_skills("Italiano nativo. Gestioné extranets de Booking.com y la auditoría "
                        "nocturna; atención al cliente y quejas de huéspedes. Euskera B2.")
    assert {"italian", "reservations", "night_audit", "customer_service", "basque"} <= set(found)
    assert "customer_success" not in found


def test_an_education_heading_is_not_teaching():
    assert "teaching" not in find_skills("FORMACIÓN\nGrado en Derecho")
    assert "teaching" in find_skills("Experiencia como formador de equipos")
