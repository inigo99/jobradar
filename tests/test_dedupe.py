"""Deduplication across sources."""

from jobradar.models import Salary, SalaryOrigin
from jobradar.pipeline.dedupe import deduplicate
from tests.conftest import make_job


def test_collapses_same_id():
    jobs = [make_job(), make_job()]
    assert len(deduplicate(jobs)) == 1


def test_collapses_same_company_and_title_across_sources():
    a = make_job(source="boarda", native_id="1")
    b = make_job(source="boardb", native_id="2")
    assert len(deduplicate([a, b])) == 1


def test_keeps_the_more_informative_record():
    thin = make_job(source="boarda", native_id="1", description="",
                    salary=Salary(origin=SalaryOrigin.UNKNOWN))
    rich = make_job(source="boardb", native_id="2", description="A full advertisement." * 20)
    survivor = deduplicate([thin, rich])[0]
    assert survivor.salary is not None
    assert survivor.salary.origin == SalaryOrigin.PUBLISHED
    description = survivor.description
    assert description is not None
    assert len(description) > 100


def test_records_where_else_it_was_seen():
    survivor = deduplicate([make_job(source="a", native_id="1"),
                            make_job(source="b", native_id="2")])[0]
    assert survivor.raw.get("also_seen_on")


def test_different_companies_are_not_merged():
    a = make_job(company="Talan", native_id="1")
    b = make_job(company="Alan", native_id="2")
    assert len(deduplicate([a, b])) == 2


def test_different_roles_at_one_company_are_not_merged():
    a = make_job(title="Backend Engineer", native_id="1")
    b = make_job(title="Marketing Manager", native_id="2")
    assert len(deduplicate([a, b])) == 2


def test_dedupe_survives_null_fields():
    a = make_job(native_id="1")
    a.title = None
    a.company = None
    b = make_job(native_id="2")
    b.title = None
    b.company = None
    assert len(deduplicate([a, b])) == 2