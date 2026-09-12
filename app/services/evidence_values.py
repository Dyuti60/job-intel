import hashlib
import json
import unicodedata
import uuid

from app.models.evidence import EvidenceType

EVIDENCE_EXCERPT_MAX_LENGTH = 8_000
EVIDENCE_CONTEXT_MAX_LENGTH = 16_000
EVIDENCE_LOCATOR_MAX_LENGTH = 1_024


def normalize_evidence_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return normalized.replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_optional_evidence_text(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_evidence_text(value) or None


def normalize_source_locator(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def compute_evidence_hash(
    *,
    source_document_id: uuid.UUID,
    source_document_content_hash: str,
    evidence_type: EvidenceType,
    source_locator: str | None,
    excerpt: str,
    context: str | None,
) -> str:
    payload = {
        "source_document": {
            "id": str(source_document_id),
            "content_hash": source_document_content_hash,
        },
        "evidence_type": evidence_type.value,
        "source_locator": normalize_source_locator(source_locator),
        "excerpt": normalize_evidence_text(excerpt),
        "context": normalize_optional_evidence_text(context),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()
