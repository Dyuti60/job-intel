from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.master import RecruitmentMaster, RecruitmentMasterStatus
from tests.factories import (
    create_ready_candidate_revision,
    decide_review_item,
    start_review_case,
)
from tests.test_master_api import _direct_graph, _new_candidate_revision, _publish
from tests.test_review_api import build_review_graph

PUBLIC_URL = "/api/public/v1/recruitments"


def _published(
    client: TestClient,
    suffix: str,
    *,
    start: str | None = "2026-09-01",
    end: str | None = "2026-09-30",
    vacancies: int | None = 10,
) -> dict:
    fields = [
        {"field_path": "post.name", "value_type": "STRING", "value": f"Post {suffix}"},
        {"field_path": "qualification.minimum", "value_type": "STRING", "value": "HSLC"},
        {"field_path": "age.minimum", "value_type": "INTEGER", "value": 18},
    ]
    if start is not None:
        fields.append(
            {"field_path": "application.start_date", "value_type": "DATE", "value": start}
        )
    if end is not None:
        fields.append({"field_path": "application.end_date", "value_type": "DATE", "value": end})
    if vacancies is not None:
        fields.append(
            {"field_path": "vacancies.total", "value_type": "INTEGER", "value": vacancies}
        )
    graph = _direct_graph(client, f"PUBLIC_{suffix}", fields)
    publication = _publish(client, graph["confidence"]["id"])
    assert publication.status_code == 201, publication.text
    return {**graph, "publication": publication.json()}


def test_public_list_and_detail_expose_only_current_approved_contract(
    client: TestClient,
) -> None:
    graph = _published(client, "CONTRACT", vacancies=42)
    master_id = graph["publication"]["master"]["id"]

    listed = client.get(PUBLIC_URL, params={"as_of": "2026-09-10"})
    detail = client.get(f"{PUBLIC_URL}/{master_id}", params={"as_of": "2026-09-10"})

    assert listed.status_code == detail.status_code == 200
    page = listed.json()
    assert page["page"] == 1 and page["page_size"] == 25
    assert page["total"] == page["pages"] == 1
    assert page["items"][0]["application"] == {
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "status": "OPEN",
        "evaluated_on": "2026-09-10",
    }
    assert page["items"][0]["vacancies_total"] == 42
    body = detail.json()
    assert body["authority"]["code"] == graph["authority"]["code"]
    assert body["current_revision_number"] == 1
    assert [field["field_path"] for field in body["fields"]] == [
        "age.minimum",
        "application.end_date",
        "application.start_date",
        "post.name",
        "qualification.minimum",
        "vacancies.total",
    ]
    source = body["sources"][0]
    assert source["document_url"] == graph["document"]["document_url"]
    assert source["source_class"] == "AUTHORITATIVE_OFFICIAL"
    assert source["authority_code"] == graph["authority"]["code"]

    forbidden = {
        "projection_hash",
        "source_candidate_field_id",
        "review_decision_id",
        "verification_run_id",
        "revision_confidence_assessment_id",
        "review_case_id",
        "storage_uri",
        "content_hash",
        "raw_value",
        "summary_json",
        "error_message",
    }
    assert forbidden.isdisjoint(body)
    assert all(forbidden.isdisjoint(field) for field in body["fields"])
    assert all(forbidden.isdisjoint(item) for item in body["sources"])


def test_unpublished_rejected_unresolved_and_inactive_records_never_leak(
    client: TestClient, db_session: Session
) -> None:
    active = _published(client, "VISIBLE")
    inactive = _published(client, "INACTIVE")
    inactive_row = db_session.get(RecruitmentMaster, UUID(inactive["publication"]["master"]["id"]))
    assert inactive_row is not None
    inactive_row.status = RecruitmentMasterStatus.INACTIVE
    db_session.commit()

    create_ready_candidate_revision(
        client,
        authority_overrides={
            "code": "PUBLIC_DRAFT",
            "official_website_url": "https://public-draft.gov.in",
        },
        endpoint_overrides={"canonical_url": "https://public-draft.gov.in/notices"},
    )
    build_review_graph(client, suffix="PUBLIC_UNRESOLVED")
    rejected = build_review_graph(client, suffix="PUBLIC_REJECTED")
    start_review_case(client, rejected["case"]["id"])
    for item in rejected["case"]["items"]:
        decide_review_item(client, item["id"], "REJECT")

    result = client.get(PUBLIC_URL)
    ids = {item["id"] for item in result.json()["items"]}

    assert result.status_code == 200
    assert ids == {active["publication"]["master"]["id"]}
    assert client.get(f"{PUBLIC_URL}/{inactive['publication']['master']['id']}").status_code == 404
    assert client.get(f"{PUBLIC_URL}/{uuid4()}").status_code == 404


def test_historical_noncurrent_revision_is_not_exposed(client: TestClient) -> None:
    graph = _published(client, "HISTORY", start=None, end=None, vacancies=None)
    first = graph["publication"]
    newer = _new_candidate_revision(
        client,
        graph,
        "public-history-v2",
        [
            {"field_path": "post.name", "value_type": "STRING", "value": "Current Post"},
            {"field_path": "description.summary", "value_type": "STRING", "value": "Current"},
            {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 1},
            {"field_path": "application.start_date", "value_type": "DATE", "value": "2026-09-01"},
            {"field_path": "application.end_date", "value_type": "DATE", "value": "2026-09-30"},
            {"field_path": "qualification.minimum", "value_type": "STRING", "value": "HSLC"},
            {"field_path": "age.minimum", "value_type": "INTEGER", "value": 18},
        ],
    )
    second = _publish(client, newer["confidence"]["id"])
    assert second.status_code == 201

    body = client.get(f"{PUBLIC_URL}/{first['master']['id']}").json()

    assert body["current_revision_number"] == 2
    assert {field["field_path"] for field in body["fields"]} == {
        "age.minimum",
        "application.end_date",
        "application.start_date",
        "description.summary",
        "post.name",
        "qualification.minimum",
        "vacancies.total",
    }
    assert "Post HISTORY" not in str(body)


def test_filters_ordering_and_pagination_are_deterministic(
    client: TestClient, db_session: Session
) -> None:
    first = _published(client, "A", end="2026-09-20", vacancies=5)
    second = _published(client, "B", end="2026-10-20", vacancies=50)
    third = _published(client, "C", start="2026-11-01", end="2026-11-20", vacancies=500)
    for index, graph in enumerate((first, second, third), start=1):
        master = db_session.get(RecruitmentMaster, UUID(graph["publication"]["master"]["id"]))
        assert master is not None
        master.last_published_at = datetime(2026, 9, index, tzinfo=UTC)
    db_session.commit()

    ordered = client.get(
        PUBLIC_URL,
        params={
            "as_of": "2026-09-10",
            "sort": "application_end_asc",
            "page": 2,
            "page_size": 1,
        },
    ).json()
    assert ordered["total"] == 3 and ordered["pages"] == 3
    assert ordered["items"][0]["candidate_key"] == second["candidate"]["candidate_key"]

    assert (
        client.get(
            PUBLIC_URL,
            params={"authority": second["authority"]["code"].lower()},
        ).json()["total"]
        == 1
    )
    assert (
        client.get(
            PUBLIC_URL,
            params={"candidate_key": third["candidate"]["candidate_key"].lower()},
        ).json()["total"]
        == 1
    )
    assert client.get(PUBLIC_URL, params={"q": "master authority public_b"}).json()["total"] == 1
    assert client.get(PUBLIC_URL, params={"q": "%"}).json()["total"] == 0
    assert (
        client.get(
            PUBLIC_URL,
            params={"as_of": "2026-09-10", "application_status": "OPEN"},
        ).json()["total"]
        == 2
    )
    assert (
        client.get(
            PUBLIC_URL,
            params={"application_end_from": "2026-10-01", "minimum_vacancies": 40},
        ).json()["total"]
        == 2
    )
    vacancies = client.get(PUBLIC_URL, params={"sort": "vacancies_desc"}).json()["items"]
    assert [item["vacancies_total"] for item in vacancies] == [500, 50, 5]


def test_application_status_is_derived_safely_at_date_boundaries(client: TestClient) -> None:
    graph = _published(client, "WINDOW", start="2026-10-01", end="2026-10-31")
    master_id = graph["publication"]["master"]["id"]

    def status_on(value: str) -> str:
        return client.get(f"{PUBLIC_URL}/{master_id}", params={"as_of": value}).json()[
            "application"
        ]["status"]

    assert status_on("2026-09-30") == "UPCOMING"
    assert status_on("2026-10-01") == "OPEN"
    assert status_on("2026-10-31") == "OPEN"
    assert status_on("2026-11-01") == "CLOSED"


def test_default_public_history_keeps_current_recent_and_unknown_but_hides_old_closed(
    client: TestClient,
) -> None:
    open_job = _published(client, "HISTORY_OPEN", start="2026-09-01", end="2026-09-30")
    upcoming = _published(client, "HISTORY_UPCOMING", start="2026-10-01", end="2026-10-31")
    recent = _published(client, "HISTORY_RECENT", start="2025-08-01", end="2025-09-14")
    old = _published(client, "HISTORY_OLD", start="2025-07-01", end="2025-09-13")
    unknown = _published(client, "HISTORY_UNKNOWN", start=None, end=None)

    api = client.get(PUBLIC_URL, params={"as_of": "2026-09-14"}).json()
    web = client.get("/jobs", params={"as_of": "2026-09-14"})
    visible = {item["candidate_key"] for item in api["items"]}

    assert visible == {
        open_job["candidate"]["candidate_key"],
        upcoming["candidate"]["candidate_key"],
        recent["candidate"]["candidate_key"],
    }
    assert f"/jobs/{old['publication']['master']['id']}" not in web.text
    assert f"/jobs/{unknown['publication']['master']['id']}" not in web.text
    old_master_id = old["publication"]["master"]["id"]
    assert client.get(f"/api/v1/recruitment-master/{old_master_id}").status_code == 200
    historical_detail = client.get(f"{PUBLIC_URL}/{old_master_id}", params={"as_of": "2026-09-14"})
    assert historical_detail.status_code == 200


def test_mismatched_current_revision_pointer_fails_closed(
    client: TestClient, db_session: Session
) -> None:
    first = _published(client, "POINTER_A")
    second = _published(client, "POINTER_B")
    first_master = db_session.get(RecruitmentMaster, UUID(first["publication"]["master"]["id"]))
    assert first_master is not None
    first_master.current_revision_id = UUID(second["publication"]["master_revision"]["id"])
    db_session.commit()

    listed = client.get(PUBLIC_URL).json()["items"]

    assert {item["id"] for item in listed} == {second["publication"]["master"]["id"]}
    assert client.get(f"{PUBLIC_URL}/{first['publication']['master']['id']}").status_code == 404


def test_public_validation_is_bounded_and_gets_are_read_only(
    client: TestClient, db_session: Session
) -> None:
    graph = _published(client, "READONLY")
    before = {
        table.name: db_session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }

    assert client.get(PUBLIC_URL, params={"page_size": 101}).status_code == 422
    assert client.get(PUBLIC_URL, params={"authority": "bad-code"}).status_code == 422
    assert client.get(PUBLIC_URL, params={"q": "x" * 101}).status_code == 422
    assert (
        client.get(
            PUBLIC_URL,
            params={"application_end_from": "2026-10-02", "application_end_to": "2026-10-01"},
        ).status_code
        == 422
    )
    assert (
        client.get(PUBLIC_URL, params={"minimum_vacancies": 10, "maximum_vacancies": 1}).status_code
        == 422
    )
    assert client.get(PUBLIC_URL).status_code == 200
    assert client.get(f"{PUBLIC_URL}/{graph['publication']['master']['id']}").status_code == 200
    assert (
        client.post(
            f"{PUBLIC_URL}/{graph['publication']['master']['id']}/eligibility", json={}
        ).status_code
        == 200
    )

    db_session.expire_all()
    after = {
        table.name: db_session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }
    assert after == before

    public_paths = {
        path: methods
        for path, methods in client.get("/openapi.json").json()["paths"].items()
        if path.startswith("/api/public/v1/")
    }
    assert public_paths
    assert all(
        set(methods) == ({"post"} if path.endswith("/eligibility") else {"get"})
        for path, methods in public_paths.items()
    )
