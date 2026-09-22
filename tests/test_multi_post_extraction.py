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
    CandidateValueType,
    PostFact,
    RecruitmentCandidateRevision,
    RecruitmentPost,
)
from app.models.discovery import DocumentType
from app.models.evidence import CandidateFieldEvidence, Evidence
from app.models.master import MasterPost
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from app.services.published_maintenance import PublishedMaintenanceService
from sources.adapters.apsc_recruitment import AdapterDocument
from sources.adapters.official_recruitment_archive import (
    OFFICIAL_ARCHIVE_SOURCES,
    ArchiveAdapterResult,
    ArchiveNotice,
    ArchiveNoticeMetadata,
    archive_candidate_key,
    extraction_diagnostic_summary,
    parse_narrative_vacancies,
    parse_official_advertisement_text,
)
from sources.extraction import ParsedField
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
        "Grade IV Staff – Assam Police",
        "Grade IV Staff – Assam Commando Battalions",
        "Grade IV Staff – DGCD & CGHG",
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


def test_rich_recruitment_sections_and_post_details_are_deterministic() -> None:
    metadata = ArchiveNoticeMetadata(
        title="Advertisement for Driver Constable and Driver Operator",
        document_url="https://slprbassam.in/pdf/rich-driver-advertisement.pdf",
        notification_number="SLPRB/REC/2026/88",
        notification_date=date(2026, 9, 14),
    )
    extraction = parse_official_advertisement_text(
        _text("rich_multi_post_advertisement.txt"),
        metadata,
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in extraction.posts] == [
        "Driver Constable – Assam Police",
        "Driver Operator – Fire & Emergency Services",
    ]
    shared = {field.field_path: field.value for field in extraction.fields}
    assert shared["application.url"] == "https://slprbassam.in/apply"
    assert shared["domicile.requirement"].startswith(
        "Candidates must be permanent residents of Assam"
    )
    assert shared["nationality.requirement"] == "Candidate must be an Indian citizen."
    assert shared["age.relaxations"] == [
        {"Category": "SC / ST", "Relaxation": "5 years"},
        {"Category": "OBC / MOBC", "Relaxation": "3 years"},
    ]
    assert shared["application.fee"] == "No application fee"
    assert shared["application.fee_exemptions"] == "All applicants"
    assert shared["application.payment_mode"] == "Not applicable"
    assert shared["application.steps"][0] == "Open https://slprbassam.in/apply."
    assert shared["application.steps"][-1].endswith("before 20/10/2026.")
    assert shared["application.documents_required"][-1] == "Valid driving licence"
    assert [phase["sequence"] for phase in shared["selection.phases"]] == [1, 2, 3, 4, 5]
    assert shared["selection.phases"][0]["name"].startswith("Physical Standard Test")
    assert shared["selection.exam_pattern"][0]["Phase"] == "Written examination"
    assert shared["syllabus.phases"][0]["Subject"] == "General Knowledge and Aptitude"

    post_facts = [{fact.field_path: fact.value for fact in post.facts} for post in extraction.posts]
    assert [facts["vacancies.total"] for facts in post_facts] == [127, 4]
    assert post_facts[0]["qualification.essential"].startswith("HSLC passed")
    assert post_facts[0]["qualification.desirable"] == "Experience driving heavy vehicles"
    assert post_facts[0]["age.minimum"] == 18
    assert post_facts[0]["age.maximum"] == 25
    assert post_facts[0]["age.reference_date"] == "2026-01-01"
    assert "162.5 cm" in post_facts[0]["physical.criteria"]
    assert "colour blindness" in post_facts[0]["medical.criteria"]
    assert post_facts[1]["qualification.desirable"] == "Fire-service driving experience"
    assert "vacancies.total" not in shared


def test_pypdf_whitespace_and_multiline_sections_are_post_isolated() -> None:
    metadata = ArchiveNoticeMetadata(
        title=(
            "Advertisement for 127 posts of Driver Constable in Assam Police and "
            "4 posts of Driver Operator in Fire & Emergency Services"
        ),
        document_url="https://slprbassam.in/pdf/pypdf-driver-advertisement.pdf",
        notification_number="SLPRB/REC/2026/99",
        notification_date=date(2026, 9, 14),
    )
    raw_text = _text("pypdf_driver_excerpt.txt")
    assert "|" not in raw_text

    extraction = parse_official_advertisement_text(
        raw_text, metadata, "State Level Police Recruitment Board, Assam"
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert extraction.warnings == ()
    assert [post.name for post in extraction.posts] == [
        "Driver Constable – Assam Police",
        "Driver Operator – Fire & Emergency Services",
    ]
    shared = {field.field_path: field.value for field in extraction.fields}
    assert shared["qualification.minimum"].startswith("HSLC or equivalent")
    assert shared["age.relaxations"] == [
        {"category": "SC / ST(P) / ST(H)", "relaxation": "5 years"},
        {"category": "OBC / MOBC", "relaxation": "3 years"},
    ]
    assert shared["domicile.requirement"].endswith("Permanent Resident of Assam")
    assert "162.5 cm" in str(shared["physical.criteria"])
    assert "3200 metres" in str(shared["physical.criteria"])
    assert "Long jump" in str(shared["physical.criteria"])
    assert "colour blindness" in str(shared["medical.criteria"])
    assert "eyesight and hearing" in str(shared["medical.criteria"])
    assert len(shared["application.documents_required"]) == 2
    assert len(shared["selection.phases"]) == 5
    assert shared["selection.exam_pattern"][0]["questions"] == 100
    assert shared["selection.exam_pattern"][0]["marks"] == 50
    assert shared["selection.exam_pattern"][0]["duration"] == "2 hours"
    assert shared["selection.exam_pattern"][0]["negative_marking"] == "None"
    assert shared["selection.exam_pattern"][0]["mode"] == "OMR answer sheet"
    assert shared["selection.exam_pattern"][0]["languages"] == [
        "Assamese",
        "Bodo",
        "Bengali",
        "English",
    ]
    assert shared["syllabus.phases"][0]["subjects"][-1] == "Logical reasoning"

    facts = [{fact.field_path: fact.value for fact in post.facts} for post in extraction.posts]
    assert facts[0]["vacancies.total"] == 127
    assert facts[0]["vacancies.tea_tribes_adivasi"] == 4
    assert facts[0]["vacancies.women"] == 10
    assert facts[0]["vacancies.ex_servicemen"] == 2
    assert facts[0]["age.maximum"] == 25
    assert facts[0]["pay.grade_pay"] == "Rs. 5600/-"
    assert facts[0]["qualification.essential"] == ("HSLC passed from recognised Board or Council")
    assert facts[0]["qualification.desirable"] == "Heavy vehicle driving experience"
    assert facts[0]["qualification.registration_or_licence"].endswith("LMV or MMV or HMV")
    assert facts[1]["vacancies.total"] == 4
    assert facts[1]["age.minimum"] == 20
    assert facts[1]["age.maximum"] == 30
    assert facts[1]["qualification.essential"] == ("HSSLC passed from recognised Board or Council")
    assert facts[1]["qualification.desirable"] == "Fire appliance driving experience"
    assert facts[1]["qualification.registration_or_licence"].endswith("for HMV")
    assert "Heavy vehicle driving experience" not in str(facts[1])
    assert "LMV" not in str(facts[1])

    diagnostic = extraction_diagnostic_summary(
        document_url=metadata.document_url,
        page_texts=raw_text.split("Page 2 of 4"),
        extraction=extraction,
    )
    assert diagnostic["pages_scanned"] == 2
    assert diagnostic["advertisement_field_paths"] == sorted(shared)
    assert [post["post_key"] for post in diagnostic["posts"]] == [
        "driver_constable_assam_police",
        "driver_operator_fire_emergency_services",
    ]
    assert diagnostic["ambiguities"] == []


def test_pypdf_post_fact_without_exact_organisation_is_left_ambiguous() -> None:
    extraction = parse_official_advertisement_text(
        """
        Advertisement for 7 posts of Driver in Assam Police and
        9 posts of Driver in Forest Department.
        5.6 EDUCATIONAL QUALIFICATION
        5.6.A For the post of Driver, Applicant must possess valid driving license for HMV.
        """,
        ArchiveNoticeMetadata(
            title=(
                "Advertisement for 7 posts of Driver in Assam Police and "
                "9 posts of Driver in Forest Department"
            ),
            document_url="https://slprbassam.in/pdf/ambiguous-driver-license.pdf",
            notification_number=None,
            notification_date=None,
        ),
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert any("licence clause" in warning for warning in extraction.warnings)
    assert all(
        "qualification.registration_or_licence" not in {fact.field_path for fact in post.facts}
        for post in extraction.posts
    )


def test_grade_iv_pypdf_uses_atomic_trade_posts_and_clean_section_ownership() -> None:
    metadata = ArchiveNoticeMetadata(
        title=(
            "Advertisement for 181 posts of Grade IV staff in Assam Police, "
            "6 posts of Grade IV staff in Assam Commando Battalions and "
            "69 posts of Grade IV staff under DGCD & CGHG"
        ),
        document_url="https://slprbassam.in/pdf/grade-iv-atomic.pdf",
        notification_number="SLPRB/REC/GRADE-IV/2026/91",
        notification_date=date(2026, 1, 16),
    )
    extraction = parse_official_advertisement_text(
        _text("pypdf_grade_iv_excerpt.txt"),
        metadata,
        "State Level Police Recruitment Board, Assam",
    )

    expected = {
        ("Cook", "Assam Police"): 115,
        ("Barber", "Assam Police"): 34,
        ("Water Carrier", "Assam Police"): 19,
        ("Dhobi", "Assam Police"): 11,
        ("Cobbler", "Assam Police"): 2,
        ("Barber", "Assam Commando Battalions"): 2,
        ("Water Carrier", "Assam Commando Battalions"): 3,
        ("Plumber", "Assam Commando Battalions"): 1,
        ("Cook", "DGCD & CGHG"): 27,
        ("Water Carrier", "DGCD & CGHG"): 11,
        ("Dhobi", "DGCD & CGHG"): 8,
        ("Barber", "DGCD & CGHG"): 12,
        ("Cobbler", "DGCD & CGHG"): 11,
    }
    actual = {}
    facts_by_name = {}
    for post in extraction.posts:
        facts = {fact.field_path: fact.value for fact in post.facts}
        organisation = facts["organisation.name"]
        actual[(post.normalized_name.title(), organisation)] = facts["vacancies.total"]
        facts_by_name[post.name] = facts
    assert actual == expected
    assert len({post.post_key for post in extraction.posts}) == 13
    assert not any(post.normalized_name == "grade iv staff" for post in extraction.posts)
    shared = {field.field_path: field.value for field in extraction.fields}
    assert shared["vacancies.total"] == 256
    assert shared["qualification.minimum"].startswith("Minimum Class VIII")
    assert shared["qualification.maximum"].startswith("HSSLC or Class XII")

    police_cook = facts_by_name["Cook – Assam Police"]
    police_barber = facts_by_name["Barber – Assam Police"]
    commando_plumber = facts_by_name["Plumber – Assam Commando Battalions"]
    assert "Cooking" in police_cook["experience.requirement"]
    assert "Saloon" not in str(police_cook)
    assert "Saloon" in police_barber["experience.requirement"]
    assert "Cooking" not in str(police_barber)
    assert "Industrial Training Institution" in commando_plumber["qualification.certificate"]
    assert police_cook["age.maximum"] == 40
    assert commando_plumber["age.maximum"] == 25
    assert commando_plumber["age.reference_date"] == "2026-01-01"
    assert police_cook["vacancies.ur"] == 60
    assert police_cook["vacancies.women"] == 12
    assert police_cook["vacancies.category_gender"][0] == {
        "category": "UR",
        "male": 54,
        "female": 6,
        "total": 60,
    }

    physical = shared["physical.criteria"]
    assert physical["height"][0]["male"] == "160 cm"
    assert physical["height"][1]["female"] == "147.5 cm"
    assert physical["chest"][0]["normal"] == "Min. 80 cm"
    assert physical["chest"][0]["categories"].endswith("ST (P)")
    assert "160 cm" not in str(shared["application.steps"])
    assert shared["application.steps"][-1].startswith("Upload necessary documents")
    assert len(shared["application.documents_required"]) == 3
    assert [phase["name"] for phase in shared["selection.phases"]] == [
        "Preliminary Identity Verification",
        "Medical Examination",
        "Physical Standard Test (PST)",
        "Trade Proficiency Test (TPT)",
        "Final Merit List",
    ]
    assert shared["selection.trade_proficiency_test"]["maximum_marks"] == 50
    assert shared["selection.final_merit"]["qualifying_percentage"] == 33
    assert "Rejection Slip" not in str(shared["selection.phases"])
    assert "colour blind" in str(shared["medical.criteria"])
    assert shared["age.relaxations"][0]["relaxation"] == "5 years"


def test_unreconciled_trade_roster_preserves_parent_posts_and_ambiguity() -> None:
    raw_text = _text("pypdf_grade_iv_excerpt.txt").replace(
        "Cook 54 6 25 3 3 0 7 1 10 1 4 1 115",
        "Cook 54 6 25 3 3 0 7 1 10 1 4 1 114",
    )
    extraction = parse_official_advertisement_text(
        raw_text,
        ArchiveNoticeMetadata(
            title=(
                "Advertisement for 181 posts of Grade IV staff in Assam Police, "
                "6 posts of Grade IV staff in Assam Commando Battalions and "
                "69 posts of Grade IV staff under DGCD & CGHG"
            ),
            document_url="https://slprbassam.in/pdf/grade-iv-unreconciled.pdf",
            notification_number=None,
            notification_date=None,
        ),
        "State Level Police Recruitment Board, Assam",
    )

    assert [post.normalized_name for post in extraction.posts] == [
        "grade iv staff",
        "grade iv staff",
        "grade iv staff",
    ]
    assert any("do not reconcile" in warning for warning in extraction.warnings)


def test_unheaded_optional_rules_are_not_fabricated() -> None:
    extraction = parse_official_advertisement_text(
        "Online applications from 20/09/2026 to 20/10/2026. No syllabus is supplied.",
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    values = {field.field_path: field.value for field in extraction.fields}
    assert "syllabus.phases" not in values
    assert "domicile.requirement" not in values
    assert "physical.criteria" not in values


def test_conflicting_repeated_sections_are_not_resolved_by_last_value() -> None:
    extraction = parse_official_advertisement_text(
        """
        AGE
        Minimum: 18 years
        Maximum: 25 years
        GENERAL CONDITIONS
        AGE
        Minimum: 20 years
        Maximum: 30 years
        """,
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    values = {field.field_path: field.value for field in extraction.fields}
    assert "age.minimum" not in values
    assert "age.maximum" not in values


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
        "Grade IV Staff – Assam Police",
        "Grade IV Staff – Assam Commando Battalions",
        "Grade IV Staff – DGCD & CGHG",
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
                ("Constable (Dispatch Rider) – APRO", "APRO", 14),
                ("Constable (Messenger) – APRO", "APRO", 20),
                ("Constable (Handymen) – APRO", "APRO", 3),
            ],
        ),
        (
            "90 posts of Driver & 4 posts of Driver Operator in Fire & Emergency Services",
            [
                ("Driver – Fire & Emergency Services", "Fire & Emergency Services", 90),
                (
                    "Driver Operator – Fire & Emergency Services",
                    "Fire & Emergency Services",
                    4,
                ),
            ],
        ),
        (
            "7 posts of Driver Constable & 106 posts of Driver in Forest Department",
            [
                ("Driver Constable – Forest Department", "Forest Department", 7),
                ("Driver – Forest Department", "Forest Department", 106),
            ],
        ),
        (
            "20 posts of Technical Assistant and 10 posts of Field Assistant in Unit X",
            [
                ("Technical Assistant – Unit X", "Unit X", 20),
                ("Field Assistant – Unit X", "Unit X", 10),
            ],
        ),
    ]
    for text, expected in cases:
        posts, status, _note, _warnings = parse_narrative_vacancies(text, text)
        actual = [
            (
                post.name,
                next(fact.value for fact in post.facts if fact.field_path == "organisation.name"),
                next(fact.value for fact in post.facts if fact.field_path == "vacancies.total"),
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
        ("Driver Constable – Assam Police", 127),
        ("Constable (Dispatch Rider) – APRO", 14),
        ("Constable (Messenger) – APRO", 20),
        ("Constable (Handymen) – APRO", 3),
        ("Driver – Fire & Emergency Services", 90),
        ("Driver Operator – Fire & Emergency Services", 4),
        ("Driver Constable – Forest Department", 7),
        ("Driver – Forest Department", 106),
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
        next(fact.value for fact in post.facts if fact.field_path == "vacancies.total") != 371
        for post in extraction.posts
    )


def test_narrative_organisation_does_not_cross_sentence_or_unrelated_clause() -> None:
    unsafe = (
        "10 posts of Constable (A). 5 posts of Constable (B) in Unit B",
        "10 posts of Constable (A), unrelated work and 5 posts of Constable (B) in Unit B",
    )
    for text in unsafe:
        posts, status, _note, _warnings = parse_narrative_vacancies(text, text)
        assert status == AdvertisementSplitStatus.AMBIGUOUS
        assert posts == ()


def test_simple_fully_qualified_narrative_names_remain_unchanged() -> None:
    text = "10 posts of Post A in Unit A and 5 posts of Post B under Unit B"
    posts, status, _note, _warnings = parse_narrative_vacancies(text, text)
    assert status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in posts] == ["Post A – Unit A", "Post B – Unit B"]


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


def test_archive_worker_persists_post_facts_and_evidence_idempotently(db_session, tmp_path) -> None:
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


def test_rich_multi_post_facts_reach_master_and_public_views(client, db_session, tmp_path) -> None:
    metadata = ArchiveNoticeMetadata(
        title="Advertisement for Driver Constable and Driver Operator",
        document_url="https://slprbassam.in/pdf/rich-driver-advertisement.pdf",
        notification_number="SLPRB/REC/2026/88",
        notification_date=date(2026, 9, 14),
    )
    content = _text("rich_multi_post_advertisement.txt").encode()
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
    confidence = _verify_revision(client, document, revision)["confidence"]
    publication = _publish(client, confidence["id"])
    assert publication.status_code == 201, publication.text

    public = client.get("/api/public/v1/recruitments", params={"as_of": "2026-09-20"}).json()
    assert public["total"] == 2
    driver = next(
        item
        for item in public["items"]
        if item["display_name"] == "Driver Constable – Assam Police"
    )
    operator = next(
        item
        for item in public["items"]
        if item["display_name"] == "Driver Operator – Fire & Emergency Services"
    )
    assert driver["vacancies_total"] == 127
    assert operator["vacancies_total"] == 4
    assert driver["organisation"] == "Assam Police"
    assert driver["qualification_summary"].startswith("HSLC passed")

    detail = client.get(f"/api/public/v1/recruitments/{driver['id']}").json()
    values = {field["field_path"]: field["value"] for field in detail["fields"]}
    assert values["qualification.essential"].startswith("HSLC passed")
    assert values["qualification.desirable"] == "Experience driving heavy vehicles"
    assert values["age.minimum"] == 18
    assert values["age.maximum"] == 25
    assert values["domicile.requirement"].startswith("Candidates must be permanent residents")
    assert values["application.documents_required"][-1] == "Valid driving licence"
    assert values["selection.phases"][2]["name"] == "Driving skill test"
    assert values["selection.exam_pattern"][0]["Phase"] == "Written examination"
    assert values["syllabus.phases"][0]["Subject"] == "General Knowledge and Aptitude"
    assert detail["sources"][0]["document_url"] == metadata.document_url

    operator_detail = client.get(f"/api/public/v1/recruitments/{operator['id']}").json()
    operator_values = {field["field_path"]: field["value"] for field in operator_detail["fields"]}
    assert operator_values["qualification.desirable"] == "Fire-service driving experience"
    assert "Experience driving heavy vehicles" not in str(operator_values)

    master_id = publication.json()["master"]["id"]
    web_detail = client.get(f"/jobs/{driver['id']}")
    summary = client.get(f"/jobs/advertisements/{master_id}")
    assert web_detail.status_code == summary.status_code == 200
    assert "Complete Official Advertisement" in web_detail.text
    assert metadata.document_url in web_detail.text
    assert summary.text.count("View Job Details") == 2
    assert "Driver Constable" in summary.text and "Driver Operator" in summary.text


def test_pypdf_like_extraction_reaches_candidate_master_and_public_detail(
    client, db_session, tmp_path
) -> None:
    metadata = ArchiveNoticeMetadata(
        title=(
            "Advertisement for 127 posts of Driver Constable in Assam Police and "
            "4 posts of Driver Operator in Fire & Emergency Services"
        ),
        document_url="https://slprbassam.in/pdf/pypdf-driver-advertisement.pdf",
        notification_number="SLPRB/REC/2026/99",
        notification_date=date(2026, 9, 14),
    )
    content = _text("pypdf_driver_excerpt.txt").encode()
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
    OfficialArchiveDiscoveryWorkerService(
        db_session,
        Settings(raw_storage_root=str(tmp_path)),
        logging.getLogger(__name__),
        OFFICIAL_ARCHIVE_SOURCES["SLPRB_ASSAM"],
    ).run(adapter=_FakeAdapter(result))

    revision_row = db_session.scalar(select(RecruitmentCandidateRevision))
    assert revision_row is not None
    revision = client.get(f"/api/v1/candidate-revisions/{revision_row.id}").json()
    assert db_session.scalar(select(func.count()).select_from(RecruitmentPost)) == 2
    document = client.get(f"/api/v1/source-documents/{revision_row.source_document_id}").json()
    assert (
        client.patch(
            f"/api/v1/recruitment-candidates/{revision_row.recruitment_candidate_id}",
            json={"status": "READY_FOR_VERIFICATION"},
        ).status_code
        == 200
    )
    confidence = _verify_revision(client, document, revision)["confidence"]
    assert _publish(client, confidence["id"]).status_code == 201

    public = client.get("/api/public/v1/recruitments", params={"as_of": "2026-01-01"}).json()
    assert public["total"] == 2
    driver = next(
        item
        for item in public["items"]
        if item["display_name"] == "Driver Constable – Assam Police"
    )
    detail = client.get(f"/api/public/v1/recruitments/{driver['id']}").json()
    values = {field["field_path"]: field["value"] for field in detail["fields"]}
    assert values["vacancies.total"] == 127
    assert values["vacancies.tea_tribes_adivasi"] == 4
    assert values["age.maximum"] == 25
    assert values["qualification.registration_or_licence"].endswith("LMV or MMV or HMV")
    assert values["application.documents_required"][1].endswith("valid driving licence.")
    assert values["selection.exam_pattern"][0]["questions"] == 100
    assert values["syllabus.phases"][0]["subjects"][0] == "Elementary Arithmetic"


def test_atomic_grade_iv_posts_reach_master_and_public_jobs(client, db_session, tmp_path) -> None:
    metadata = ArchiveNoticeMetadata(
        title=(
            "Advertisement for 181 posts of Grade IV staff in Assam Police, "
            "6 posts of Grade IV staff in Assam Commando Battalions and "
            "69 posts of Grade IV staff under DGCD & CGHG"
        ),
        document_url="https://slprbassam.in/pdf/grade-iv-atomic.pdf",
        notification_number="SLPRB/REC/GRADE-IV/2026/91",
        notification_date=date(2026, 1, 16),
    )
    content = _text("pypdf_grade_iv_excerpt.txt").encode()
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
    OfficialArchiveDiscoveryWorkerService(
        db_session,
        Settings(raw_storage_root=str(tmp_path)),
        logging.getLogger(__name__),
        OFFICIAL_ARCHIVE_SOURCES["SLPRB_ASSAM"],
    ).run(adapter=_FakeAdapter(result))

    revision_row = db_session.scalar(select(RecruitmentCandidateRevision))
    assert revision_row is not None
    assert db_session.scalar(select(func.count()).select_from(RecruitmentPost)) == 13
    revision = client.get(f"/api/v1/candidate-revisions/{revision_row.id}").json()
    document = client.get(f"/api/v1/source-documents/{revision_row.source_document_id}").json()
    assert (
        client.patch(
            f"/api/v1/recruitment-candidates/{revision_row.recruitment_candidate_id}",
            json={"status": "READY_FOR_VERIFICATION"},
        ).status_code
        == 200
    )
    confidence = _verify_revision(client, document, revision)["confidence"]
    assert _publish(client, confidence["id"]).status_code == 201

    public = client.get("/api/public/v1/recruitments", params={"as_of": "2026-01-22"}).json()
    assert public["total"] == 13
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 13
    assert not any(item["display_name"].startswith("Grade IV Staff") for item in public["items"])
    dgcd_cook = next(
        item for item in public["items"] if item["display_name"] == "Cook – DGCD & CGHG"
    )
    assert dgcd_cook["vacancies_total"] == 27
    detail = client.get(f"/api/public/v1/recruitments/{dgcd_cook['id']}").json()
    values = {field["field_path"]: field["value"] for field in detail["fields"]}
    assert values["vacancies.total"] == 27
    assert values["vacancies.ur"] == 15
    assert "Cooking" in values["experience.requirement"]
    assert values["qualification.maximum"].startswith("HSSLC or Class XII")
    assert "160 cm" not in str(values["application.steps"])


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
                fields=(
                    *extraction.fields,
                    ParsedField(
                        field_path="qualification.minimum",
                        value_type=CandidateValueType.STRING,
                        value="Class VIII",
                        raw_value="Class VIII",
                        source_locator="fixture:eligibility",
                        excerpt="Minimum qualification: Class VIII",
                    ),
                    ParsedField(
                        field_path="age.minimum",
                        value_type=CandidateValueType.INTEGER,
                        value=18,
                        raw_value="18",
                        source_locator="fixture:eligibility",
                        excerpt="Minimum age: 18 years",
                    ),
                ),
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
    public = client.get("/api/public/v1/recruitments", params={"as_of": "2026-09-20"}).json()
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 3
    assert len(master_posts) == public["total"] == 3, [
        row["missing"] for row in PublishedMaintenanceService(db_session).rows()
    ]
    assert len({post["public_id"] for post in master_posts}) == 3
    expected = {
        "Grade IV Staff – Assam Police": 181,
        "Grade IV Staff – Assam Commando Battalions": 6,
        "Grade IV Staff – DGCD & CGHG": 69,
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

    advertisement_id = publication.json()["master"]["id"]
    summary = client.get(f"/jobs/advertisements/{advertisement_id}")
    assert summary.status_code == 200
    assert summary.text.count("View Job Details") == 3
    assert "Grade IV Staff – Assam Police" in summary.text
    assert "Grade IV Staff – Assam Commando Battalions" in summary.text
    assert "Grade IV Staff – DGCD &amp; CGHG" in summary.text
    assert metadata.document_url in summary.text
    for item in public["items"]:
        assert f"/jobs/{item['id']}" in summary.text


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
        ]
        + [
            {"field_path": "qualification.minimum", "value_type": "STRING", "value": "Class VIII"},
            {"field_path": "age.minimum", "value_type": "INTEGER", "value": 18},
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

    public = client.get("/api/public/v1/recruitments", params={"as_of": "2026-09-20"}).json()
    history = client.get(f"/api/v1/recruitment-master/{first['master']['id']}/revisions").json()
    assert second["master"]["id"] == first["master"]["id"]
    assert second["master_revision"]["revision_number"] == 2
    assert len(history) == 2
    assert public["total"] == 8
    assert legacy_public_id not in {item["id"] for item in public["items"]}
    assert client.get(f"/api/public/v1/recruitments/{legacy_public_id}").status_code == 404
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 8
