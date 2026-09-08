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
