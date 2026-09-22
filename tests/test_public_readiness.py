from app.services.public_readiness import (
    JobCompletenessStatus,
    evaluate_public_readiness,
)

BASE_SHARED = {
    "application.start_date": "2026-09-01",
    "application.end_date": "2026-09-30",
    "qualification.minimum": "HSLC",
    "age.minimum": 18,
}
BASE_POST = {"vacancies.total": 10}


def readiness(*, shared=None, post=None, name="Post", source="https://assam.gov.in/job.pdf"):
    return evaluate_public_readiness(
        post_name=name,
        official_source_url=source,
        shared=BASE_SHARED if shared is None else shared,
        post=BASE_POST if post is None else post,
    )


def test_complete_public_readiness_ignores_optional_salary() -> None:
    assert readiness().status == JobCompletenessStatus.COMPLETE
    assert readiness().missing == ()


def test_required_public_fields_are_reported_exactly() -> None:
    assert readiness(post={}).missing == ("Post vacancies",)
    for path, label in (
        ("application.start_date", "Opening date"),
        ("application.end_date", "Closing date"),
        ("qualification.minimum", "Qualification"),
        ("age.minimum", "Age criteria"),
    ):
        shared = {key: value for key, value in BASE_SHARED.items() if key != path}
        assert label in readiness(shared=shared).missing


def test_advertisement_total_does_not_satisfy_explicit_post_vacancies() -> None:
    shared = {**BASE_SHARED, "advertisement.vacancies.total": 100}
    result = readiness(shared=shared, post={})
    assert result.status == JobCompletenessStatus.PARTIAL
    assert result.missing == ("Post vacancies",)
