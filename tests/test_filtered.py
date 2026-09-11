"""Rejected ads are kept, not thrown away — and can be put back."""

from __future__ import annotations

from datetime import date

from jobradar.config import Filters
from jobradar.models import Salary, SalaryOrigin
from jobradar.pipeline.filters import apply_filters, category, shape
from tests.conftest import make_job

TODAY = date(2026, 9, 11)


def test_shape_blanks_the_numbers_so_reasons_group():
    assert shape("published 9 days ago (limit 7)") == shape("published 21 days ago (limit 7)")


def test_category_points_at_the_setting_to_change():
    assert category("salary ≈ 30,000 EUR (below 45,000 EUR)") == "salary"
    assert category("asks for 8 years, you have 3") == "experience"
    assert category("excluded keyword 'sales'") == "keywords"


def test_a_rejected_job_is_stored_with_its_reason(database):
    job = make_job(salary=Salary(minimum=20000, maximum=25000, currency="EUR",
                                 origin=SalaryOrigin.PUBLISHED))
    outcome = apply_filters(job, Filters(min_salary=45000), today=TODAY)
    assert not outcome.keep

    database.save_filtered([(job, outcome.reason, category(outcome.reason))])
    stored = database.list_filtered()
    assert len(stored) == 1
    assert stored[0]["id"] == job.id
    assert stored[0]["category"] == "salary"
    assert "below" in stored[0]["reason"]


def test_storing_the_same_job_twice_does_not_duplicate_it(database):
    """A rerun re-rejects the same ads; the list is a state, not a log."""
    job = make_job()
    database.save_filtered([(job, "excluded keyword 'x'", "keywords")])
    database.save_filtered([(job, "excluded keyword 'x'", "keywords")])
    assert len(database.list_filtered()) == 1


def test_the_tally_counts_by_category_and_by_shape(database):
    database.save_filtered([
        (make_job(native_id="1"), "salary ≈ 30,000 EUR (below 45,000 EUR)", "salary"),
        (make_job(native_id="2"), "salary ≈ 31,000 EUR (below 45,000 EUR)", "salary"),
        (make_job(native_id="3"), "asks for 8 years, you have 3", "experience"),
    ])
    tally = database.filtered_tally()
    assert tally["by_category"][0] == ("salary", 2)
    # The two salary reasons differ only in their numbers, so they group.
    assert tally["by_shape"][0][1] == 2


def test_restoring_puts_the_job_back_on_the_board(database):
    job = make_job()
    database.save_filtered([(job, "salary too low", "salary")])
    restored = database.restore_filtered(job.id)

    assert restored is not None
    assert database.get_job(job.id) is not None
    assert database.list_filtered() == []


def test_restoring_something_that_is_not_there_returns_none(database):
    assert database.restore_filtered("test:nope") is None


def test_clearing_empties_the_list(database):
    database.save_filtered([(make_job(), "whatever", "other")])
    database.clear_filtered()
    assert database.list_filtered() == []
