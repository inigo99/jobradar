"""The recruiter red-flag linter."""

from jobradar.lint import lint_profile
from jobradar.models import Bullet, Experience, Profile


def profile_with(*experiences: Experience) -> Profile:
    profile = Profile()
    profile.contact.full_name = "Alex Morgan"
    profile.contact.email = "alex@example.com"
    profile.contact.phone = "+34 600 000 000"
    profile.summary = {"en": "Engineer who cut errors by 47%."}
    profile.experience = list(experiences)
    return profile


def role(identifier, organisation, start, end, bullets):
    return Experience(
        id=identifier, title={"en": "Engineer"}, organization=organisation,
        start=start, end=end,
        bullets=[Bullet(id=f"{identifier}-{i}", text={"en": text})
                 for i, text in enumerate(bullets)],
    )


def rules_fired(result):
    return {finding.rule for finding in result.findings}


def test_flags_reverse_chronology():
    result = lint_profile(profile_with(
        role("a", "Old Corp", "2018-01", "2020-01", ["Cut errors by 40%."]),
        role("b", "New Corp", "2021-01", None, ["Cut latency by 30%."]),
    ))
    assert "chronology" in rules_fired(result)


def test_flags_an_unexplained_gap():
    result = lint_profile(profile_with(
        role("b", "New Corp", "2023-06", None, ["Cut latency by 30%."]),
        role("a", "Old Corp", "2018-01", "2020-01", ["Cut errors by 40%."]),
    ))
    assert "employment-gap" in rules_fired(result)


def test_flags_duty_language_and_missing_metrics():
    result = lint_profile(profile_with(
        role("a", "Corp", "2022-01", None,
             ["Responsible for the maintenance of internal tools.",
              "Worked on the reporting module."]),
    ))
    fired = rules_fired(result)
    assert "duty-language" in fired
    assert "few-metrics" in fired


def test_flags_empty_phrases():
    profile = profile_with(role("a", "Corp", "2022-01", None, ["Cut errors by 47%."]))
    profile.summary = {"en": "Results-driven team player and detail-oriented professional."}
    assert "empty-phrase" in rules_fired(lint_profile(profile))


def test_clean_profile_scores_well():
    result = lint_profile(profile_with(
        role("b", "New Corp", "2022-03", None,
             ["Cut checkout errors by 47% by introducing an integration test suite.",
              "Enabled 1200 stores to sync stock by designing REST APIs."]),
        role("a", "Old Corp", "2020-06", "2022-02",
             ["Cut weekly reporting effort by 12 hours by automating the ETL."]),
    ))
    assert result.score() >= 90
    assert not result.errors
