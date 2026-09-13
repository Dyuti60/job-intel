import logging
import uuid
from datetime import date

from sqlalchemy import func, select

from app.models.candidates import (
    CandidateField,
    CandidateStatus,
    CandidateValueType,
    RecruitmentCandidateRevision,
)
from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    RevisionConfidenceAssessment,
)
from app.models.evidence import Evidence, EvidenceType
from app.models.review import ReviewCase
from app.models.review_routing import ReviewRoutingAssessment
from app.models.verification import (
    EvidenceAssessmentType,
    FieldVerification,
    FieldVerificationOutcome,
    VerificationRun,
)
from app.services.candidate_field_evidence_verifier import CandidateFieldEvidenceVerifier
from app.services.verification_worker import VerificationWorkerService
from tests.factories import (
    create_candidate,
    create_discovery_source,
    create_evidence,
    create_revision,
    create_run,
    observe_document,
)


def _models(path: str, value_type: CandidateValueType, value, excerpt: str):
    field = CandidateField(field_path=path, value_type=value_type, value=value)
    evidence = Evidence(evidence_type=EvidenceType.TEXT_EXCERPT, excerpt=excerpt)
    return field, evidence


def test_deterministic_date_integer_string_and_contradiction_rules() -> None:
    verifier = CandidateFieldEvidenceVerifier()
    field, evidence = _models(
        "application.end_date",
        CandidateValueType.DATE,
        "2026-09-10",
        "Application End Date : 10/09/2026 Midnight. Last date for fee: 12/09/2026",
    )
    result = verifier.evaluate(field, evidence)
    assert (result.assessment, result.asserted_value, result.asserted_value_type) == (
        EvidenceAssessmentType.SUPPORTS,
        date(2026, 9, 10).isoformat(),
        CandidateValueType.DATE,
    )

    field, evidence = _models(
        "vacancies.total", CandidateValueType.INTEGER, 1, "No of posts:-01 (One) no."
    )
    assert verifier.evaluate(field, evidence).assessment == EvidenceAssessmentType.SUPPORTS

    field, evidence = _models(
        "eligibility.minimum_age",
        CandidateValueType.INTEGER,
        21,
        "Minimum age: 18 years",
    )
    result = verifier.evaluate(field, evidence)
    assert result.assessment == EvidenceAssessmentType.CONTRADICTS
    assert result.asserted_value == 18

    field, evidence = _models(
        "recruitment_name",
        CandidateValueType.STRING,
        "Research Assistant",
        "RESEARCH   ASSISTANT under Labour Welfare Department",
    )
    assert verifier.evaluate(field, evidence).assessment == EvidenceAssessmentType.SUPPORTS


def test_integer_ambiguity_and_unsupported_summary_are_context_only() -> None:
    verifier = CandidateFieldEvidenceVerifier()
    field, evidence = _models(
        "vacancies.total",
        CandidateValueType.INTEGER,
        10,
        "No of posts: 10. Revised number of posts: 12.",
    )
    assert verifier.evaluate(field, evidence).assessment == EvidenceAssessmentType.CONTEXT_ONLY

    field, evidence = _models(
        "vacancies.total",
        CandidateValueType.INTEGER,
        50,
        "Advertisement for 47 posts of Sub Inspector and 3 posts of Constable.",
    )
    result = verifier.evaluate(field, evidence)
    assert result.assessment == EvidenceAssessmentType.SUPPORTS
    assert result.asserted_value == 50

    field, evidence = _models(
        "eligibility.qualification.summary",
        CandidateValueType.STRING,
        "Bachelor degree in Science",
        "Graduates may apply subject to the official conditions.",
    )
    assert verifier.evaluate(field, evidence).assessment == EvidenceAssessmentType.CONTEXT_ONLY


def _seed_candidate(client, *, code: str = "APSC", key: str = "APSC_ADVT_12_2026"):
    authority, endpoint = create_discovery_source(
        client,
        authority_overrides={
            "code": code,
            "name": f"{code} Authority",
            "official_website_url": f"https://{code.lower()}.example.gov.in",
        },
        endpoint_overrides={
            "canonical_url": f"https://{code.lower()}.example.gov.in/recruitment",
            "source_class": "AUTHORITATIVE_OFFICIAL",
        },
    )
    discovery_run = create_run(client, endpoint["id"])
    document = observe_document(
        client,
        discovery_run["id"],
        document_url=f"https://{code.lower()}.example.gov.in/advt.pdf",
        content_text="controlled immutable official content",
    )["document"]
    candidate = create_candidate(client, authority["id"], candidate_key=key)
    fields = [
        {
            "field_path": "application.end_date",
            "value_type": "DATE",
            "value": "2026-09-10",
        },
        {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 1},
        {
            "field_path": "recruitment_name",
            "value_type": "STRING",
            "value": "Research Assistant",
        },
    ]
    revision = create_revision(client, candidate["id"], document["id"], fields=fields)
    excerpts = {
        "application.end_date": "Application End Date : 10/09/2026 Midnight",
        "vacancies.total": "No of posts:-01 (One) no.",
        "recruitment_name": "Research Assistant under Labour Welfare Department",
    }
    for field in revision["fields"]:
        evidence = create_evidence(
            client,
            document["id"],
            excerpt=excerpts[field["field_path"]],
            source_locator=f"fixture:{field['field_path']}",
        )
        response = client.post(
            f"/api/v1/candidate-fields/{field['id']}/evidence/{evidence['id']}"
        )
        assert response.status_code == 201, response.text
    return candidate, revision


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_worker_transitions_draft_verifies_scores_and_is_idempotent(
    client, db_session, monkeypatch
) -> None:
    candidate, revision = _seed_candidate(client)

    def fail_network(*args, **kwargs):
        raise AssertionError("Verification worker must not issue HTTP requests")

    import httpx

    monkeypatch.setattr(httpx.Client, "request", fail_network)
    worker = VerificationWorkerService(db_session, logging.getLogger(__name__))
    first = worker.run(
        authority="APSC", candidate_key=None, batch_size=100, dry_run=False
    )
    assert first.completed == 1
    assert first.fields_confirmed == 3
    assert first.fields_insufficient == 0
    assert first.no_review_required == 1
    assert first.review_cases_queued == 0
    db_session.expire_all()
    from app.models.candidates import RecruitmentCandidate

    assert (
        db_session.get(RecruitmentCandidate, uuid.UUID(candidate["id"])).status
        == CandidateStatus.READY_FOR_VERIFICATION
    )
    assert _count(db_session, VerificationRun) == 1
    assert _count(db_session, FieldVerification) == 3
    assert _count(db_session, FieldConfidenceAssessment) == 6
    assert _count(db_session, RevisionConfidenceAssessment) == 2
    assert _count(db_session, ReviewRoutingAssessment) == 1
    assert {
        item.policy_version
        for item in db_session.scalars(select(RevisionConfidenceAssessment)).all()
    } == {ConfidencePolicyVersion.V1, ConfidencePolicyVersion.V2}

    second = worker.run(
        authority="APSC", candidate_key=None, batch_size=100, dry_run=False
    )
    assert second.revisions_scanned == 0
    assert _count(db_session, VerificationRun) == 1
    assert _count(db_session, ReviewRoutingAssessment) == 1


def test_worker_routes_insufficient_evidence_once(client, db_session) -> None:
    _, revision = _seed_candidate(client)
    authority = client.get("/api/v1/source-authorities").json()[0]
    candidate = create_candidate(client, authority["id"], candidate_key="APSC_NO_EVIDENCE")
    document_id = revision["source_document_id"]
    no_evidence = create_revision(
        client,
        candidate["id"],
        document_id,
        fields=[
            {
                "field_path": "application.end_date",
                "value_type": "DATE",
                "value": "2026-09-10",
            }
        ],
    )
    summary = VerificationWorkerService(db_session).run(
        authority="APSC", candidate_key="APSC_NO_EVIDENCE", batch_size=100, dry_run=False
    )
    assert summary.fields_insufficient == 1
    assert summary.review_cases_queued == 1
    assert _count(db_session, ReviewCase) == 1
    routing = db_session.scalar(select(ReviewRoutingAssessment))
    assert routing.review_required is True
    assert "INSUFFICIENT_CRITICAL_EVIDENCE" in routing.reason_codes
    assert "UNCLEAR_CRITICAL_MEANING" in routing.reason_codes
    verification = db_session.scalar(
        select(FieldVerification).where(
            FieldVerification.candidate_field_id
            == uuid.UUID(no_evidence["fields"][0]["id"])
        )
    )
    assert verification.outcome == FieldVerificationOutcome.INSUFFICIENT_EVIDENCE

    review_case = client.get("/api/v1/review-cases").json()[0]
    assert client.post(f"/api/v1/review-cases/{review_case['id']}/start").status_code == 200
    detail = client.get(f"/api/v1/review-cases/{review_case['id']}").json()
    for index, item in enumerate(detail["items"]):
        decision = "REQUEST_REVERIFICATION" if index == 0 else "APPROVE_AS_IS"
        payload = {
            "decision": decision,
            "reviewer_identifier": "worker-test",
        }
        if decision == "REQUEST_REVERIFICATION":
            payload["decision_note"] = "Run deterministic verification once more."
        response = client.post(f"/api/v1/review-items/{item['id']}/decision", json=payload)
        assert response.status_code == 201, response.text

    db_session.rollback()
    retry = VerificationWorkerService(db_session).run(
        authority="APSC", candidate_key="APSC_NO_EVIDENCE", batch_size=100, dry_run=False
    )
    assert retry.completed == 1
    assert _count(db_session, VerificationRun) == 2
    assert _count(db_session, ReviewCase) == 2
    replay = VerificationWorkerService(db_session).run(
        authority="APSC", candidate_key="APSC_NO_EVIDENCE", batch_size=100, dry_run=False
    )
    assert replay.revisions_scanned == 0


def test_dry_run_and_batch_selection_leave_no_mutation(client, db_session) -> None:
    first_candidate, _ = _seed_candidate(client)
    _seed_candidate(client, code="APSC2", key="APSC2_ADVT_1_2026")
    worker = VerificationWorkerService(db_session)
    selected = worker.select_eligible_revisions(
        authority=None, candidate_key=None, batch_size=1
    )
    expected = db_session.scalar(
        select(RecruitmentCandidateRevision.id).order_by(
            RecruitmentCandidateRevision.created_at,
            RecruitmentCandidateRevision.id,
        )
    )
    assert selected == [expected]
    summary = worker.run(
        authority="APSC", candidate_key=None, batch_size=100, dry_run=True
    )
    assert summary.completed == 1
    assert _count(db_session, VerificationRun) == 0
    from app.models.candidates import RecruitmentCandidate

    db_session.expire_all()
    assert (
        db_session.get(RecruitmentCandidate, uuid.UUID(first_candidate["id"])).status
        == CandidateStatus.DRAFT
    )
