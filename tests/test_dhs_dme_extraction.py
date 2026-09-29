from datetime import date
from pathlib import Path

import pytest

from app.models.candidates import AdvertisementSplitStatus
from sources.adapters.official_recruitment_archive import (
    ArchiveNoticeMetadata,
    parse_official_advertisement_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dhs_dme"


def _metadata(title: str) -> ArchiveNoticeMetadata:
    return ArchiveNoticeMetadata(
        title=title,
        document_url="https://dme.assam.gov.in/documents/recruitment.pdf",
        notification_number="DME/RECT/2026/1",
        notification_date=date(2026, 6, 30),
    )


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _facts(extraction):
    return [{fact.field_path: fact.value for fact in post.facts} for post in extraction.posts]


def test_dhs_whitespace_vacancies_create_isolated_posts() -> None:
    raw_text = _text("dhs_whitespace_vacancies.txt")
    metadata = _metadata("Advertisement-Staff Nurse(Critical Care) & ICU Technician")

    first = parse_official_advertisement_text(raw_text, metadata, "DHS Assam")
    repeated = parse_official_advertisement_text(raw_text, metadata, "DHS Assam")

    assert first.split_status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in first.posts] == [
        "Staff Nurse(Critical Care)",
        "ICU Technician",
    ]
    assert [facts["vacancies.total"] for facts in _facts(first)] == [484, 125]
    assert [post.post_key for post in first.posts] == [post.post_key for post in repeated.posts]
    assert _facts(first)[0]["vacancies.total"] != _facts(first)[1]["vacancies.total"]
    shared = {field.field_path: field.value for field in first.fields}
    assert shared["application.start_date"] == "2026-06-30"
    assert shared["application.end_date"] == "2026-07-15"
    assert all("application.end_date" not in facts for facts in _facts(first))


def test_dme_numbered_positions_map_each_explicit_count() -> None:
    raw_text = _text("dme_numbered_positions.txt")
    metadata = _metadata("Recruitment of staff for PIU at DME & PWD")

    extraction = parse_official_advertisement_text(raw_text, metadata, "DME Assam")
    repeated = parse_official_advertisement_text(raw_text, metadata, "DME Assam")

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in extraction.posts] == [
        "Project Management Specialist",
        "Assistant Finance Specialist (AFS)",
        "Assistant Engineer (AE)",
    ]
    assert [facts["vacancies.total"] for facts in _facts(extraction)] == [1, 1, 1]
    assert len({post.post_key for post in extraction.posts}) == 3
    assert [post.post_key for post in extraction.posts] == [
        post.post_key for post in repeated.posts
    ]


@pytest.mark.parametrize("authority", ["DHS Assam", "DME Assam"])
def test_explicit_single_post_title_is_safe_without_fabricating_vacancy(authority: str) -> None:
    extraction = parse_official_advertisement_text(
        "Applications are invited for filling up the position on contractual basis.",
        _metadata("Advertisement for the post of Director, SCI, Guwahati"),
        authority,
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in extraction.posts] == ["Director, SCI, Guwahati"]
    assert "vacancies.total" not in _facts(extraction)[0]


def test_incomplete_whitespace_table_is_ambiguous_and_creates_no_posts() -> None:
    extraction = parse_official_advertisement_text(
        _text("ambiguous_whitespace_vacancies.txt"),
        _metadata("Advertisement for Grade-III Technical Posts"),
        "DME Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.AMBIGUOUS
    assert extraction.posts == ()
    assert "no deterministic pay/total boundary" in (extraction.split_note or "")


def test_unsupported_advertisement_remains_legacy_unsplit() -> None:
    extraction = parse_official_advertisement_text(
        "Applications are invited. See the official annexure for position details.",
        _metadata("Advertisement"),
        "DHS Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.LEGACY_UNSPLIT
    assert extraction.posts == ()


def test_single_post_title_conflicting_with_multi_post_body_is_ambiguous() -> None:
    extraction = parse_official_advertisement_text(
        "Applications are invited for the following technical posts shown below.",
        _metadata("Advertisement for the post of Technical Staff"),
        "DHS Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.AMBIGUOUS
    assert extraction.posts == ()
