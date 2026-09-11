"""The years ceiling: taken from the CV, with a band for "just short"."""

from __future__ import annotations

from datetime import date

from jobradar.config import Filters
from jobradar.pipeline.filters import apply_filters
from tests.conftest import make_job

TODAY = date(2026, 9, 11)


def test_an_ad_that_states_no_years_is_never_filtered_on_years():
    """Most ads state none. Treating silence as a rejection empties the board."""
    outcome = apply_filters(make_job(min_years_experience=None), Filters(),
                            today=TODAY, profile_years=3.0)
    assert outcome.keep


def test_the_ceiling_comes_from_the_profile_when_nothing_is_typed():
    outcome = apply_filters(make_job(min_years_experience=8), Filters(),
                            today=TODAY, profile_years=3.0)
    assert not outcome.keep
    assert "you have 3" in outcome.reason


def test_an_explicit_number_still_wins():
    """A user who typed a number meant it."""
    outcome = apply_filters(make_job(min_years_experience=8),
                            Filters(max_years_experience=10),
                            today=TODAY, profile_years=3.0)
    assert outcome.keep


def test_turning_the_profile_ceiling_off_disables_the_rule():
    outcome = apply_filters(make_job(min_years_experience=20),
                            Filters(use_profile_years=False),
                            today=TODAY, profile_years=3.0)
    assert outcome.keep


def test_just_short_is_separated_from_far_out_of_reach():
    near = apply_filters(make_job(min_years_experience=4), Filters(years_margin=1.0),
                         today=TODAY, profile_years=3.0)
    far = apply_filters(make_job(min_years_experience=9), Filters(years_margin=1.0),
                        today=TODAY, profile_years=3.0)
    assert "just short" in near.reason
    assert "just short" not in far.reason


def test_exactly_meeting_the_requirement_passes():
    outcome = apply_filters(make_job(min_years_experience=3), Filters(),
                            today=TODAY, profile_years=3.0)
    assert outcome.keep


def test_without_a_profile_the_rule_does_nothing():
    outcome = apply_filters(make_job(min_years_experience=15), Filters(),
                            today=TODAY, profile_years=None)
    assert outcome.keep
