import logging
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.candidates import (
    AdvertisementRevision,
    AdvertisementSplitStatus,
    PostFact,
    RecruitmentCandidateRevision,
    RecruitmentPost,
)
from app.models.discovery import DocumentType
from app.models.evidence import CandidateFieldEvidence, Evidence
from app.models.master import MasterPost
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from sources.adapters.apsc_recruitment import AdapterDocument
from sources.adapters.official_recruitment_archive import (
    OFFICIAL_ARCHIVE_SOURCES,
    ArchiveAdapterResult,
    ArchiveNotice,
    ArchiveNoticeMetadata,
    archive_candidate_key,
    parse_narrative_vacancies,
    parse_official_advertisement_text,
)
from sources.http import FetchedResource
from tests.factories import (
    create_ready_candidate_revision,
    create_revision,
    create_run,
    observe_document,
)
from tests.test_master_api import _publish, _verify_revision

FIXTURES = Path(__file__).parent / "fixtures" / "slprb"


def _metadata() -> ArchiveNoticeMetadata:
    return ArchiveNoticeMetadata(
        title="Advertisement for Grade IV Staff",
        document_url="https://slprbassam.in/pdf/grade-iv-2026.pdf",
        notification_number="SLPRB/REC/2026/44",
        notification_date=date(2026, 9, 14),
    )


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_multi_post_vacancy_table_is_explicit_and_preserves_shared_facts() -> None:
    extraction = parse_official_advertisement_text(
        _text("multi_post_advertisement.txt"),
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in extraction.posts] == [
        "Grade IV Staff - Assam Police",
        "Grade IV Staff - Assam Commando Battalions",
        "Grade IV Staff - DGCD & CGHG",
    ]
    assert [
        next(fact.value for fact in post.facts if fact.field_path == "vacancies.total")
        for post in extraction.posts
    ] == [181, 6, 69]
    assert [post.post_key for post in extraction.posts] == [
        "grade_iv_staff_assam_police",
        "grade_iv_staff_assam_commando_battalions",
        "grade_iv_staff_dgcd_cghg",
    ]
    assert all(
        next(fact.value for fact in post.facts if fact.field_path == "qualification.minimum")
        == "Class VIII passed"
        for post in extraction.posts
    )
    shared = {field.field_path: field.value for field in extraction.fields}
    assert shared["application.start_date"] == "2026-09-20"
    assert shared["application.end_date"] == "2026-10-20"
    assert "vacancies.total" not in shared


def test_realistic_slprb_narrative_extracts_three_qualified_posts() -> None:
    metadata = ArchiveNoticeMetadata(
        title=(
            "Advertisement for 181 posts of Grade IV staff in Assam Police, "
            "6 posts of Grade IV staff in Assam Commando Battalions and "
            "69 posts of Grade IV staff under DGCD & CGHG"
        ),
        document_url="https://slprbassam.in/pdf/grade-iv-narrative.pdf",
        notification_number="SLPRB/REC/2026/47",
        notification_date=date(2026, 9, 14),
    )
    extraction = parse_official_advertisement_text(
        _text("narrative_multi_post_advertisement.txt"),
        metadata,
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in extraction.posts] == [
        "Grade IV Staff - Assam Police",
        "Grade IV Staff - Assam Commando Battalions",
        "Grade IV Staff - DGCD & CGHG",
    ]
    assert [
        next(fact.value for fact in post.facts if fact.field_path == "vacancies.total")
        for post in extraction.posts
    ] == [181, 6, 69]
    shared = {field.field_path: field.value for field in extraction.fields}
    assert shared["vacancies.total"] == 256
    assert shared["application.start_date"] == "2026-09-20"
    assert shared["application.end_date"] == "2026-10-20"


def test_partial_narrative_series_is_ambiguous_and_creates_no_posts() -> None:
    extraction = parse_official_advertisement_text(
        (
            "10 posts of Grade IV staff in Assam Police and "
            "5 posts of Driver with no deterministic organization"
        ),
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.AMBIGUOUS
    assert extraction.posts == ()
    assert "split completely and safely" in (extraction.split_note or "")


def test_narrative_trailing_organisation_qualifiers_are_group_bounded() -> None:
    cases = [
        (
            "14 posts of Constable (Dispatch Rider), 20 posts of Constable "
            "(Messenger) & 3 posts of Constable (Handymen) in APRO",
            [
                ("Constable (Dispatch Rider) - APRO", "APRO", 14),
                ("Constable (Messenger) - APRO", "APRO", 20),
                ("Constable (Handymen) - APRO", "APRO", 3),
            ],
        ),
        (
            "90 posts of Driver & 4 posts of Driver Operator in Fire & Emergency Services",
            [
                ("Driver - Fire & Emergency Services", "Fire & Emergency Services", 90),
                (
                    "Driver Operator - Fire & Emergency Services",
                    "Fire & Emergency Services",
                    4,
                ),
            ],
        ),
        (
            "7 posts of Driver Constable & 106 posts of Driver in Forest Department",
            [
                ("Driver Constable - Forest Department", "Forest Department", 7),
                ("Driver - Forest Department", "Forest Department", 106),
            ],
        ),
        (
            "20 posts of Technical Assistant and 10 posts of Field Assistant in Unit X",
            [
                ("Technical Assistant - Unit X", "Unit X", 20),
                ("Field Assistant - Unit X", "Unit X", 10),
            ],
        ),
    ]
    for text, expected in cases:
        posts, status, _note, _warnings = parse_narrative_vacancies(text, text)
        actual = [
            (
                post.name,
                next(
                    fact.value
                    for fact in post.facts
                    if fact.field_path == "organisation.name"
                ),
                next(
                    fact.value
                    for fact in post.facts
                    if fact.field_path == "vacancies.total"
                ),
            )
            for post in posts
        ]
        assert status == AdvertisementSplitStatus.EXPLICIT
        assert actual == expected


def test_complete_grouped_narrative_extracts_eight_posts_and_aggregate() -> None:
    title = (
        "Advertisement for 127 posts of Driver Constable in Assam Police, "
        "14 posts of Constable (Dispatch Rider), 20 posts of Constable (Messenger) & "
        "3 posts of Constable (Handymen) in APRO and 90 posts of Driver & "
        "4 posts of Driver Operator in Fire & Emergency Services and "
        "7 posts of Driver Constable & 106 posts of Driver in Forest Department"
    )
    metadata = ArchiveNoticeMetadata(
        title=title,
        document_url="https://slprbassam.in/pdf/grouped-driver-posts.pdf",
        notification_number="SLPRB/REC/2026/48",
        notification_date=date(2026, 9, 14),
    )

    extraction = parse_official_advertisement_text(
        _text("grouped_narrative_vacancies.txt"),
        metadata,
        "State Level Police Recruitment Board, Assam",
    )

    expected = [
        ("Driver Constable - Assam Police", 127),
        ("Constable (Dispatch Rider) - APRO", 14),
        ("Constable (Messenger) - APRO", 20),
        ("Constable (Handymen) - APRO", 3),
        ("Driver - Fire & Emergency Services", 90),
        ("Driver Operator - Fire & Emergency Services", 4),
        ("Driver Constable - Forest Department", 7),
        ("Driver - Forest Department", 106),
    ]
    actual = [
        (
            post.name,
            next(fact.value for fact in post.facts if fact.field_path == "vacancies.total"),
        )
        for post in extraction.posts
    ]
    shared = {field.field_path: field.value for field in extraction.fields}
    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert actual == expected
    assert len({post.post_key for post in extraction.posts}) == 8
    assert shared["vacancies.total"] == 371
    assert all(
        next(fact.value for fact in post.facts if fact.field_path == "vacancies.total")
        != 371
        for post in extraction.posts
    )


def test_narrative_organisation_does_not_cross_sentence_or_unrelated_clause() -> None:
    unsafe = (
        "10 posts of Constable (A). 5 posts of Constable (B) in Unit B",
        "10 posts of Constable (A), unrelated work and "
        "5 posts of Constable (B) in Unit B",
    )
    for text in unsafe:
        posts, status, _note, _warnings = parse_narrative_vacancies(text, text)
        assert status == AdvertisementSplitStatus.AMBIGUOUS
        assert posts == ()


def test_simple_fully_qualified_narrative_names_remain_unchanged() -> None:
    text = "10 posts of Post A in Unit A and 5 posts of Post B under Unit B"
    posts, status, _note, _warnings = parse_narrative_vacancies(text, text)
    assert status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in posts] == ["Post A", "Post B"]


def test_malformed_vacancy_table_is_ambiguous_and_fabricates_no_posts() -> None:
    extraction = parse_official_advertisement_text(
        _text("ambiguous_vacancy_table.txt"),
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.AMBIGUOUS
    assert extraction.posts == ()
    assert "expected 9" in extraction.split_note
    assert extraction.warnings


def test_ambiguous_post_detail_ownership_is_retained_without_guessing() -> None:
    extraction = parse_official_advertisement_text(
        _text("ambiguous_post_details.txt"),
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert len(extraction.posts) == 2
    assert all(
        "qualification.minimum" not in {fact.field_path for fact in post.facts}
        for post in extraction.posts
    )
    ambiguity = next(
        field for field in extraction.fields if field.field_path == "extraction.ambiguities"
    )
    assert ambiguity.value == [
        "Post detail row at pdf:table=post-details-8;row=1 matches 2 vacancy posts"
    ]
    assert extraction.warnings == tuple(ambiguity.value)


class _FakeAdapter:
    def __init__(self, result: ArchiveAdapterResult) -> None:
        self.result = result

    def discover(self) -> ArchiveAdapterResult:
        return self.result


def _resource(url: str, content: bytes, content_type: str) -> FetchedResource:
    return FetchedResource(
        url=url,
        content=content,
        content_type=content_type,
        status_code=200,
        etag=None,
        last_modified=None,
        retrieved_at=datetime(2026, 9, 14, tzinfo=UTC),
    )


def test_archive_worker_persists_post_facts_and_evidence_idempotently(
    db_session, tmp_path
) -> None:
    metadata = _metadata()
    content = _text("multi_post_advertisement.txt").encode()
    extraction = parse_official_advertisement_text(
        content.decode(), metadata, "State Level Police Recruitment Board, Assam"
    )
    result = ArchiveAdapterResult(
        listing_document=AdapterDocument(
            _resource("https://slprbassam.in/", b"<html>official</html>", "text/html"),
            DocumentType.HTML,
            "html",
        ),
        notices=(
            ArchiveNotice(
                metadata=metadata,
                document=AdapterDocument(
                    _resource(metadata.document_url, content, "application/pdf"),
                    DocumentType.PDF,
                    "pdf",
                ),
                candidate_key=archive_candidate_key("SLPRB_ASSAM", metadata),
                fields=extraction.fields,
                posts=extraction.posts,
                split_status=extraction.split_status,
                split_note=extraction.split_note,
            ),
        ),
        warnings=(),
    )
    worker = OfficialArchiveDiscoveryWorkerService(
        db_session,
        Settings(raw_storage_root=str(tmp_path)),
        logging.getLogger(__name__),
        OFFICIAL_ARCHIVE_SOURCES["SLPRB_ASSAM"],
    )

    first = worker.run(adapter=_FakeAdapter(result))
    second = worker.run(adapter=_FakeAdapter(result))

    interpretation = db_session.scalar(select(AdvertisementRevision))
    assert interpretation.split_status == AdvertisementSplitStatus.EXPLICIT
    assert interpretation.detected_post_count == 3
    assert db_session.scalar(select(func.count()).select_from(RecruitmentPost)) == 3
    assert db_session.scalar(select(func.count()).select_from(PostFact)) == 36
    assert db_session.scalar(select(func.count()).select_from(Evidence)) == 37
    assert db_session.scalar(select(func.count()).select_from(CandidateFieldEvidence)) == 43
    assert first.revisions_created == 1
    assert second.revisions_reused == 1


def test_slprb_narrative_publishes_three_isolated_master_posts_and_public_jobs(
    client, db_session, tmp_path
) -> None:
    metadata = ArchiveNoticeMetadata(
        title=(
            "Advertisement for 181 posts of Grade IV staff in Assam Police, "
            "6 posts of Grade IV staff in Assam Commando Battalions and "
            "69 posts of Grade IV staff under DGCD & CGHG"
        ),
        document_url="https://slprbassam.in/pdf/grade-iv-narrative.pdf",
        notification_number="SLPRB/REC/2026/47",
        notification_date=date(2026, 9, 14),
    )
    content = _text("narrative_multi_post_advertisement.txt").encode()
    extraction = parse_official_advertisement_text(
        content.decode(), metadata, "State Level Police Recruitment Board, Assam"
    )
    result = ArchiveAdapterResult(
        listing_document=AdapterDocument(
            _resource("https://slprbassam.in/", b"<html>official</html>", "text/html"),
            DocumentType.HTML,
            "html",
        ),
        notices=(
            ArchiveNotice(
                metadata=metadata,
                document=AdapterDocument(
                    _resource(metadata.document_url, content, "application/pdf"),
                    DocumentType.PDF,
                    "pdf",
                ),
                candidate_key=archive_candidate_key("SLPRB_ASSAM", metadata),
                fields=extraction.fields,
                posts=extraction.posts,
                split_status=extraction.split_status,
                split_note=extraction.split_note,
            ),
        ),
        warnings=(),
    )
    worker = OfficialArchiveDiscoveryWorkerService(
        db_session,
        Settings(raw_storage_root=str(tmp_path)),
        logging.getLogger(__name__),
        OFFICIAL_ARCHIVE_SOURCES["SLPRB_ASSAM"],
    )
    worker.run(adapter=_FakeAdapter(result))

    revision_row = db_session.scalar(select(RecruitmentCandidateRevision))
    assert revision_row is not None
    revision = client.get(f"/api/v1/candidate-revisions/{revision_row.id}").json()
    document = client.get(f"/api/v1/source-documents/{revision_row.source_document_id}").json()
    ready = client.patch(
        f"/api/v1/recruitment-candidates/{revision_row.recruitment_candidate_id}",
        json={"status": "READY_FOR_VERIFICATION"},
    )
    assert ready.status_code == 200
    verified = _verify_revision(client, document, revision)
    publication = _publish(client, verified["confidence"]["id"])
    assert publication.status_code == 201, publication.text

    master_posts = publication.json()["master_revision"]["posts"]
    public = client.get(
        "/api/public/v1/recruitments", params={"as_of": "2026-09-20"}
    ).json()
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 3
    assert len(master_posts) == public["total"] == 3
    assert len({post["public_id"] for post in master_posts}) == 3
    expected = {
        "Grade IV Staff - Assam Police": 181,
        "Grade IV Staff - Assam Commando Battalions": 6,
        "Grade IV Staff - DGCD & CGHG": 69,
    }
    assert {item["display_name"]: item["vacancies_total"] for item in public["items"]} == expected

    for item in public["items"]:
        detail = client.get(
            f"/api/public/v1/recruitments/{item['id']}",
            params={"as_of": "2026-09-20"},
        ).json()
        values = {field["field_path"]: field["value"] for field in detail["fields"]}
        assert values["name"] == item["display_name"]
        assert values["vacancies.total"] == expected[item["display_name"]]
        assert values["advertisement.vacancies.total"] == 256
        assert values["application.start_date"] == "2026-09-20"
        assert values["application.end_date"] == "2026-10-20"
        assert detail["sources"][0]["document_url"] == metadata.document_url
        assert sum(field["field_path"] == "vacancies.total" for field in detail["fields"]) == 1


def test_explicit_revision_supersedes_unsplit_public_view_without_deleting_history(
    client: TestClient, db_session: Session
) -> None:
    authority, document, candidate, legacy_revision = create_ready_candidate_revision(
        client,
        fields=[
            {
                "field_path": "recruitment_name",
                "value_type": "STRING",
                "value": "Grouped Driver Advertisement",
            },
            {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 371},
        ],
        authority_overrides={
            "code": "SLPRB_GROUPED_SUPERSEDE",
            "name": "State Level Police Recruitment Board, Assam",
            "official_website_url": "https://slprbassam.in",
        },
        endpoint_overrides={"canonical_url": "https://slprbassam.in/notices"},
    )
    first_verified = _verify_revision(client, document, legacy_revision)
    first = _publish(client, first_verified["confidence"]["id"]).json()
    legacy_public_id = first["master"]["id"]

    discovery = create_run(client, document["source_endpoint_id"])
    updated_document = observe_document(
        client,
        discovery["id"],
        document_url="https://slprbassam.in/pdf/grouped-driver-posts-v2.pdf",
        content_text="grouped driver advertisement with explicit post mapping",
    )["document"]
    extraction = parse_official_advertisement_text(
        _text("grouped_narrative_vacancies.txt"),
        ArchiveNoticeMetadata(
            title=(
                "Advertisement for 127 posts of Driver Constable in Assam Police, "
                "14 posts of Constable (Dispatch Rider), 20 posts of Constable (Messenger) & "
                "3 posts of Constable (Handymen) in APRO and 90 posts of Driver & "
                "4 posts of Driver Operator in Fire & Emergency Services and "
                "7 posts of Driver Constable & 106 posts of Driver in Forest Department"
            ),
            document_url=updated_document["document_url"],
            notification_number=None,
            notification_date=None,
        ),
        authority["name"],
    )
    explicit_revision = create_revision(
        client,
        candidate["id"],
        updated_document["id"],
        fields=[
            {
                "field_path": field.field_path,
                "value_type": field.value_type.value,
                "value": field.value,
            }
            for field in extraction.fields
        ],
        split_status="EXPLICIT",
        posts=[
            {
                "post_key": post.post_key,
                "ordinal": post.ordinal,
                "name": post.name,
                "facts": [
                    {
                        "field_path": fact.field_path,
                        "value_type": fact.value_type.value,
                        "value": fact.value,
                    }
                    for fact in post.facts
                ],
            }
            for post in extraction.posts
        ],
    )
    verified = _verify_revision(client, updated_document, explicit_revision)
    second = _publish(client, verified["confidence"]["id"]).json()

    public = client.get(
        "/api/public/v1/recruitments", params={"as_of": "2026-09-20"}
    ).json()
    history = client.get(
        f"/api/v1/recruitment-master/{first['master']['id']}/revisions"
    ).json()
    assert second["master"]["id"] == first["master"]["id"]
    assert second["master_revision"]["revision_number"] == 2
    assert len(history) == 2
    assert public["total"] == 8
    assert legacy_public_id not in {item["id"] for item in public["items"]}
    assert client.get(f"/api/public/v1/recruitments/{legacy_public_id}").status_code == 404
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 8
