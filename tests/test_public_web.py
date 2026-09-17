from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.discovery import SourceDocument
from app.models.master import RecruitmentMaster, RecruitmentMasterRevision, RecruitmentMasterStatus
from app.models.source_registry import SourceEndpoint
from tests.factories import create_ready_candidate_revision
from tests.test_master_api import _direct_graph, _publish
from tests.test_public_recruitments_api import _published


def test_public_jobs_page_has_accessible_empty_and_filtered_results(client: TestClient) -> None:
    empty = client.get("/jobs")
    assert empty.status_code == 200
    assert "No approved jobs found" in empty.text
    assert 'href="#main-content"' in empty.text

    first = _published(client, "WEB_A", end="2026-10-20", vacancies=25)
    second = _published(client, "WEB_B", end="2026-11-20", vacancies=100)
    page = client.get(
        "/jobs",
        params={
            "authority": second["authority"]["code"].lower(),
            "as_of": "2026-09-10",
            "page_size": 1,
        },
    )

    assert page.status_code == 200
    assert second["candidate"]["display_name"] in page.text
    assert first["candidate"]["candidate_key"] not in page.text
    assert "Open" in page.text
    assert "100" in page.text
    assert '<form class="search-panel" method="get"' in page.text
    assert '<link rel="canonical" href="http://testserver/jobs">' in page.text


def test_public_jobs_form_accepts_blank_optional_filters(client: TestClient) -> None:
    response = client.get(
        "/jobs",
        params={
            "q": "",
            "authority": "",
            "application_status": "",
            "application_end_from": "",
            "application_end_to": "",
            "minimum_vacancies": "",
            "sort": "published_desc",
        },
    )

    assert response.status_code == 200
    assert "No approved jobs found" in response.text


def test_public_jobs_form_renders_friendly_validation_error(client: TestClient) -> None:
    response = client.get("/jobs", params={"application_end_from": "not-a-date"})

    assert response.status_code == 422
    assert "Invalid search" in response.text
    assert "Application closing date must be a valid date" in response.text


def test_public_jobs_pagination_preserves_filters(client: TestClient) -> None:
    _published(client, "PAGE_A")
    _published(client, "PAGE_B")

    response = client.get(
        "/jobs",
        params={"q": "Recruitment", "sort": "display_name_asc", "page_size": 1},
    )

    assert response.status_code == 200
    assert "Page 1 of 2" in response.text
    assert "q=Recruitment" in response.text
    assert "sort=display_name_asc" in response.text
    assert "page=2" in response.text


def test_public_cards_and_detail_use_candidate_focused_hierarchy(client: TestClient) -> None:
    from tests.test_review_web import _three_post_review_graph

    graph = _three_post_review_graph(client)
    case_id = graph['case']['id']
    client.post(f'/review/cases/{case_id}/quick-publish', data={
        'post': 'assam_police', 'comment': 'Checked official source',
    })
    cards = client.get('/jobs', params={'authority': graph['candidate'].get('authority_code', ''),
                                      'minimum_vacancies': 1, 'as_of': '2026-09-22'})
    assert 'candidate-key' not in cards.text
    assert 'REVIEW_THREE_POSTS' not in cards.text
    assert 'SLPRB Grade IV Advertisement' not in cards.text
    assert 'Parent Advertisement' in cards.text
    assert '181' in cards.text and '20 Oct 2026' in cards.text
    assert 'Advanced filters' in cards.text and 'name="minimum_vacancies" value="1"' in cards.text
    listing = client.get('/api/public/v1/recruitments').json()
    detail = client.get(f"/jobs/{listing['items'][0]['id']}")
    assert 'Job sections' in detail.text
    assert 'href="#section-age"' in detail.text
    assert 'href="#section-physical-medical"' not in detail.text
    assert 'href="#sources-heading"' in detail.text
    assert '<h3>Post Name</h3>' not in detail.text
    assert '<h3>Total Vacancies</h3>' not in detail.text
    assert 'Official source' in detail.text


def test_public_job_detail_shows_approved_fields_and_safe_source_links(
    client: TestClient,
) -> None:
    graph = _published(client, "DETAIL", end="2026-10-31", vacancies=42)
    master_id = graph["publication"]["master"]["id"]

    response = client.get(f"/jobs/{master_id}", params={"as_of": "2026-10-01"})

    assert response.status_code == 200
    assert graph["candidate"]["display_name"] in response.text
    assert "Application overview" in response.text
    assert "Important Dates" in response.text
    assert "Closing Date" in response.text
    assert "31 October 2026" in response.text
    assert "Post vacancies" in response.text
    assert "AUTHORITATIVE" not in response.text
    assert "Authoritative Official" in response.text
    assert graph["document"]["document_url"] in response.text
    assert 'target="_blank" rel="noopener noreferrer"' in response.text
    assert "review_decision" not in response.text
    assert "projection_hash" not in response.text


def test_public_detail_renders_rich_master_fields_before_eligibility_and_official_pdf(
    client: TestClient,
) -> None:
    graph = _direct_graph(
        client,
        "RICH_DETAIL",
        [
            {
                "field_path": "recruitment_name",
                "value_type": "STRING",
                "value": "Driver Recruitment",
            },
            {
                "field_path": "qualification.essential",
                "value_type": "STRING",
                "value": "HSLC and a valid driving licence",
            },
            {"field_path": "age.minimum", "value_type": "INTEGER", "value": 18},
            {
                "field_path": "age.relaxations",
                "value_type": "JSON",
                "value": [{"category": "SC/ST", "relaxation": "5 years"}],
            },
            {
                "field_path": "physical.criteria",
                "value_type": "JSON",
                "value": {
                    "height": [{"category": "General", "male_cm": 160, "female_cm": 150}],
                    "chest": [{"category": "General", "normal_cm": 80, "expansion_cm": 5}],
                    "weight": "Proportionate to height and age",
                },
            },
            {
                "field_path": "medical.criteria",
                "value_type": "STRING",
                "value": "Must be medically fit",
            },
            {
                "field_path": "application.steps",
                "value_type": "JSON",
                "value": ["Open the official portal", "Submit before the closing date"],
            },
            {
                "field_path": "application.documents_required",
                "value_type": "JSON",
                "value": ["Age proof", "Driving licence"],
            },
            {
                "field_path": "selection.phases",
                "value_type": "JSON",
                "value": [{"sequence": 1, "name": "Physical Standard Test"}],
            },
            {
                "field_path": "selection.exam_pattern",
                "value_type": "JSON",
                "value": [{"phase": "Written examination", "marks": "100"}],
            },
            {
                "field_path": "syllabus.phases",
                "value_type": "JSON",
                "value": [{"phase": "Written examination", "subject": "General Knowledge"}],
            },
        ],
    )
    publication = _publish(client, graph["confidence"]["id"]).json()
    master_id = publication["master"]["id"]

    detail = client.get(f"/jobs/{master_id}")
    summary = client.get(f"/jobs/advertisements/{master_id}")

    assert detail.status_code == summary.status_code == 200
    assert "Essential Qualification" in detail.text
    assert "Physical Standards" in detail.text
    assert "Medical Standards" in detail.text
    assert "Official Application Steps" in detail.text
    assert 'class="type-label"' not in detail.text
    assert '<ol class="recruitment-list">' in detail.text
    assert '<ul class="recruitment-list">' in detail.text
    assert '<dl class="structured-facts">' in detail.text
    assert '5 years' in detail.text
    assert 'Male Cm' in detail.text and '<td>160</td>' in detail.text
    assert 'Normal Cm' in detail.text and 'Proportionate to height and age' in detail.text
    assert '<pre>' not in detail.text
    assert "Documents Required" in detail.text
    assert "Recruitment Phases" in detail.text
    assert "Exam Pattern / Syllabus" in detail.text
    assert detail.text.index("Educational Qualification") < detail.text.index(
        "Check deterministic eligibility"
    )
    assert "Advertisement Summary" in detail.text
    assert "Complete Official Advertisement" in detail.text
    assert graph["document"]["document_url"] in detail.text
    assert graph["document"]["document_url"] in summary.text
    assert "Posts in this Advertisement" in summary.text


def test_public_web_hides_unpublished_and_inactive_records(
    client: TestClient, db_session: Session
) -> None:
    published = _published(client, "WEB_INACTIVE")
    master = db_session.get(RecruitmentMaster, UUID(published["publication"]["master"]["id"]))
    assert master is not None
    master.status = RecruitmentMasterStatus.ARCHIVED
    db_session.commit()
    _, _, candidate, _ = create_ready_candidate_revision(
        client,
        authority_overrides={
            "code": "WEB_UNPUBLISHED",
            "official_website_url": "https://web-unpublished.gov.in",
        },
        endpoint_overrides={"canonical_url": "https://web-unpublished.gov.in/notices"},
    )

    listing = client.get("/jobs")
    inactive_detail = client.get(f"/jobs/{master.id}")
    unknown = client.get(f"/jobs/{uuid4()}")

    assert listing.status_code == 200
    assert published["candidate"]["candidate_key"] not in listing.text
    assert candidate["candidate_key"] not in listing.text
    assert inactive_detail.status_code == 404
    assert unknown.status_code == 404
    assert "This approved job is not available" in unknown.text


def test_public_web_escapes_master_and_source_content(
    client: TestClient, db_session: Session
) -> None:
    graph = _direct_graph(
        client,
        "WEB_ESCAPE",
        [{"field_path": "description.summary", "value_type": "STRING", "value": "<b>value</b>"}],
    )
    publication = _publish(client, graph["confidence"]["id"]).json()
    master = db_session.get(RecruitmentMaster, UUID(publication["master"]["id"]))
    revision = db_session.get(RecruitmentMasterRevision, UUID(publication["master_revision"]["id"]))
    document = db_session.get(SourceDocument, UUID(graph["document"]["id"]))
    assert master is not None and revision is not None and document is not None
    endpoint = db_session.get(SourceEndpoint, document.source_endpoint_id)
    assert endpoint is not None
    master.display_name = revision.display_name = "<script>alert(1)</script>"
    endpoint.name = "<img src=x onerror=alert(2)>"
    db_session.commit()

    detail = client.get(f"/jobs/{master.id}")

    assert detail.status_code == 200
    assert "<script>alert(1)</script>" not in detail.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail.text
    assert "<b>value</b>" not in detail.text
    assert "&lt;b&gt;value&lt;/b&gt;" in detail.text
    assert "<img src=x" not in detail.text
    assert "&lt;img src=x onerror=alert(2)&gt;" in detail.text


def test_public_web_gets_are_read_only_and_no_mutation_route_exists(
    client: TestClient, db_session: Session
) -> None:
    graph = _published(client, "WEB_READONLY")
    before = {
        table.name: db_session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }

    assert client.get("/jobs").status_code == 200
    assert client.get(f"/jobs/{graph['publication']['master']['id']}").status_code == 200
    assert client.post("/jobs").status_code == 405
    assert client.post(f"/jobs/{graph['publication']['master']['id']}").status_code == 405

    db_session.expire_all()
    after = {
        table.name: db_session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }
    assert after == before
