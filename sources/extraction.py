from dataclasses import dataclass
from typing import Any

from app.models.candidates import AdvertisementSplitStatus, CandidateValueType


@dataclass(frozen=True)
class ParsedField:
    field_path: str
    value_type: CandidateValueType
    value: Any
    raw_value: str
    source_locator: str
    excerpt: str
    context: str | None = None


@dataclass(frozen=True)
class ParsedPost:
    post_key: str
    ordinal: int
    name: str
    normalized_name: str
    source_locator: str
    facts: tuple[ParsedField, ...]


@dataclass(frozen=True)
class ParsedAdvertisement:
    fields: tuple[ParsedField, ...]
    posts: tuple[ParsedPost, ...] = ()
    split_status: AdvertisementSplitStatus = AdvertisementSplitStatus.LEGACY_UNSPLIT
    split_note: str | None = None
    warnings: tuple[str, ...] = ()
