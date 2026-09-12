import uuid
from datetime import UTC, datetime

from app.models.evidence import EvidenceType
from app.services.evidence_values import compute_evidence_hash


def evidence_hash(**overrides) -> str:
    values = {
        "source_document_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "source_document_content_hash": "a" * 64,
        "evidence_type": EvidenceType.TEXT_EXCERPT,
        "source_locator": "page=4",
        "excerpt": "Café eligibility text",
        "context": "Age limits",
    }
    values.update(overrides)
    return compute_evidence_hash(**values)


def test_same_canonical_input_produces_same_hash() -> None:
    assert evidence_hash() == evidence_hash()


def test_line_endings_and_unicode_normalize_identically() -> None:
    assert evidence_hash(excerpt=" Cafe\u0301\r\neligibility text ") == evidence_hash(
        excerpt="Café\neligibility text"
    )


def test_changed_evidence_identity_inputs_change_hash() -> None:
    baseline = evidence_hash()

    assert evidence_hash(excerpt="Different") != baseline
    assert evidence_hash(context="Different") != baseline
    assert evidence_hash(source_locator="page=5") != baseline
    assert evidence_hash(evidence_type=EvidenceType.TABLE_FRAGMENT) != baseline
    assert evidence_hash(source_document_id=uuid.uuid4()) != baseline
    assert evidence_hash(source_document_content_hash="b" * 64) != baseline


def test_timestamps_are_not_part_of_evidence_hash() -> None:
    before = datetime.now(UTC)
    first = evidence_hash()
    after = datetime.now(UTC)
    second = evidence_hash()

    assert before <= after
    assert first == second
