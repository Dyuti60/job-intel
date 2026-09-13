import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.models.candidates import CandidateValueType
from sources.adapters.apsc_recruitment import (
    _partition_apsc_fields,
    candidate_key,
    parse_advertisement_text,
    parse_portal_feed,
)
from sources.http import (
    BoundedHttpClient,
    InvalidContentTypeError,
    ResponseTooLargeError,
    SourceFetchError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "apsc" / "whats_new_12_2026.json"


def test_portal_parser_discovers_narrow_target_and_ddmmyyyy_deadline() -> None:
    fields = {field.field_path: field for field in parse_portal_feed(FIXTURE.read_bytes())}
    assert fields["recruitment_name"].value == "Research Assistant under Labour Welfare Department"
    assert fields["notification.number"].value == "12/2026"
    assert fields["application.end_date"].value == "2026-09-10"
    assert fields["application.end_date"].value_type == CandidateValueType.DATE
    assert fields["application.end_date"].source_locator == "portal:whats-new:advt-12-2026"


def test_candidate_key_is_deterministic() -> None:
    assert candidate_key(" 12 / 2026 ") == "APSC_ADVT_12_2026"
    assert candidate_key("012/2026") == "APSC_ADVT_12_2026"
    with pytest.raises(ValueError):
        candidate_key("Research Assistant")


def test_bounded_official_pdf_text_fixture_parses_supported_typed_fields() -> None:
    text = (FIXTURE.parent / "advertisement_12_2026.txt").read_text(encoding="utf-8")
    fields = {field.field_path: field for field in parse_advertisement_text(text)}
    assert fields["notification.date"].value == "2026-08-04"
    assert fields["vacancies.total"].value == 1
    assert fields["application.start_date"].value == "2026-08-11"
    assert fields["application.end_date"].value == "2026-09-10"
    assert fields["eligibility.minimum_age"].value == 21
    assert fields["eligibility.maximum_age"].value == 38
    assert fields["eligibility.age_cutoff_date"].value == "2026-01-01"
    assert fields["pay.scale"].source_locator == "pdf:label=pay.scale"


def test_supported_apsc_advertisement_is_partitioned_into_one_explicit_post() -> None:
    text = (FIXTURE.parent / "advertisement_12_2026.txt").read_text(encoding="utf-8")

    advertisement_fields, posts = _partition_apsc_fields(parse_advertisement_text(text))

    assert {field.field_path for field in advertisement_fields} == {
        "application.end_date",
        "application.mode",
        "application.start_date",
        "notification.date",
        "notification.number",
        "recruitment_name",
    }
    assert len(posts) == 1
    assert posts[0].post_key == "research_assistant_labour_welfare"
    assert {fact.field_path for fact in posts[0].facts} >= {
        "name",
        "vacancies.total",
        "qualification.minimum",
        "age.minimum",
        "age.maximum",
        "pay.scale",
    }


def _client(handler, *, retries: int = 2, limit: int = 1024) -> BoundedHttpClient:
    return BoundedHttpClient(
        connect_timeout=1,
        read_timeout=1,
        retries=retries,
        max_response_bytes=limit,
        transport=httpx.MockTransport(handler),
    )


def test_http_retries_transient_500_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            500 if calls == 1 else 200,
            request=request,
            headers={"content-type": "application/json"},
            content=b"{}",
        )

    with _client(handler) as client:
        assert (
            client.fetch("https://example.test/feed", accepted_types=("application/json",)).content
            == b"{}"
        )
    assert calls == 2


def test_http_does_not_retry_404() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    with _client(handler) as client, pytest.raises(SourceFetchError):
        client.fetch("https://example.test/missing", accepted_types=("text/html",))
    assert calls == 1


def test_http_handles_timeout_type_and_size_limits() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("late", request=request)

    with _client(timeout, retries=0) as client, pytest.raises(SourceFetchError):
        client.fetch("https://example.test/late", accepted_types=("text/html",))

    def wrong_type(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, request=request, headers={"content-type": "image/png"}, content=b"x"
        )

    with _client(wrong_type) as client, pytest.raises(InvalidContentTypeError):
        client.fetch("https://example.test/image", accepted_types=("application/pdf",))

    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, request=request, headers={"content-type": "text/html"}, content=b"12345"
        )

    with _client(oversized, limit=4) as client, pytest.raises(ResponseTooLargeError):
        client.fetch("https://example.test/large", accepted_types=("text/html",))


def test_fixture_is_minimal_valid_json() -> None:
    assert json.loads(FIXTURE.read_text(encoding="utf-8"))["success"] is True
    assert datetime.now(UTC).tzinfo is not None
