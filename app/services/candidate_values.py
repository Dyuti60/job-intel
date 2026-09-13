import hashlib
import json
import unicodedata
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.candidates import CandidateValueType


def normalize_typed_value(value_type: CandidateValueType, value: Any) -> Any:
    if value_type == CandidateValueType.NULL:
        if value is not None:
            raise ValueError("NULL fields must have a null value")
        return None
    if value is None:
        raise ValueError(f"{value_type.value} fields cannot have a null value")

    if value_type == CandidateValueType.STRING:
        if not isinstance(value, str):
            raise ValueError("STRING fields require a string value")
        return unicodedata.normalize("NFC", value)
    if value_type == CandidateValueType.INTEGER:
        if type(value) is not int:
            raise ValueError("INTEGER fields require an integer value")
        return value
    if value_type == CandidateValueType.DECIMAL:
        return _normalize_decimal(value)
    if value_type == CandidateValueType.BOOLEAN:
        if type(value) is not bool:
            raise ValueError("BOOLEAN fields require a boolean value")
        return value
    if value_type == CandidateValueType.DATE:
        if not isinstance(value, str):
            raise ValueError("DATE fields require an ISO date string")
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as error:
            raise ValueError("DATE fields require a valid ISO date") from error
    if value_type == CandidateValueType.DATETIME:
        return _normalize_datetime(value)
    if value_type == CandidateValueType.JSON:
        return _normalize_json(value)
    raise ValueError(f"Unsupported candidate value type: {value_type}")


def compute_revision_hash(
    *,
    source_document_id: uuid.UUID,
    source_document_content_hash: str,
    fields: Iterable[tuple[str, CandidateValueType, Any]],
    posts: Iterable[dict[str, Any]] = (),
    interpretation: dict[str, Any] | None = None,
) -> str:
    canonical_fields = [
        {
            "field_path": field_path,
            "value_type": value_type.value,
            "value": value,
        }
        for field_path, value_type, value in sorted(fields, key=lambda field: field[0])
    ]
    canonical_payload: dict[str, Any] = {
        "source_document": {
            "id": str(source_document_id),
            "content_hash": source_document_content_hash,
        },
        "fields": canonical_fields,
    }
    canonical_posts = sorted(posts, key=lambda post: (post["ordinal"], post["post_key"]))
    # Keep the pre-post-domain payload byte-for-byte compatible for legacy advertisement-only
    # revisions. This is required for idempotent replay of every historical extraction.
    if canonical_posts:
        canonical_payload["posts"] = canonical_posts
    if interpretation is not None:
        canonical_payload["advertisement_interpretation"] = interpretation
    serialized = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def compute_persisted_revision_hash(revision: Any) -> str:
    """Reconstruct the canonical hash from a fully loaded persisted revision graph."""
    interpretation = revision.advertisement_revision
    posts = []
    interpretation_payload = None
    if interpretation is not None:
        posts = [
            {
                "post_key": post.post_key,
                "ordinal": post.ordinal,
                "name": post.name,
                "normalized_name": post.normalized_name,
                "fact_keys": sorted(fact.fact_key for fact in post.facts),
            }
            for post in interpretation.posts
        ]
        if interpretation.split_status.value != "LEGACY_UNSPLIT":
            interpretation_payload = {"split_status": interpretation.split_status.value}
    return compute_revision_hash(
        source_document_id=revision.source_document_id,
        source_document_content_hash=revision.source_document.content_hash,
        fields=[(field.field_path, field.value_type, field.value) for field in revision.fields],
        posts=posts,
        interpretation=interpretation_payload,
    )


def _normalize_decimal(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("DECIMAL fields require a decimal string or integer")
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("DECIMAL fields require a valid decimal value") from error
    if not decimal_value.is_finite():
        raise ValueError("DECIMAL fields require a finite value")
    normalized = format(decimal_value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if Decimal(normalized) == 0:
        return "0"
    return normalized


def _normalize_datetime(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("DATETIME fields require an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("DATETIME fields require a valid ISO datetime") from error
    if parsed.tzinfo is None:
        raise ValueError("DATETIME fields must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize_json(value: Any) -> Any:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("JSON fields require a JSON-compatible value") from error
    return json.loads(serialized)
