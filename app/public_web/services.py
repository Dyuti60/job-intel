import json
from dataclasses import dataclass
from typing import Any

from app.schemas.public_recruitments import (
    PublicRecruitmentDetail,
    PublicRecruitmentFieldRead,
)


@dataclass(frozen=True)
class PublicFieldView:
    field_path: str
    label: str
    value_type: str
    display_value: str
    source_url: str


@dataclass(frozen=True)
class PublicRecruitmentDetailView:
    recruitment: PublicRecruitmentDetail
    fields: tuple[PublicFieldView, ...]


class PublicRecruitmentViewService:
    """Format an already-approved public DTO for HTML without domain decisions."""

    @classmethod
    def detail(cls, recruitment: PublicRecruitmentDetail) -> PublicRecruitmentDetailView:
        return PublicRecruitmentDetailView(
            recruitment=recruitment,
            fields=tuple(cls._field(field) for field in recruitment.fields),
        )

    @classmethod
    def _field(cls, field: PublicRecruitmentFieldRead) -> PublicFieldView:
        return PublicFieldView(
            field_path=field.field_path,
            label=" ".join(
                part.capitalize()
                for part in field.field_path.replace(".", " ").replace("_", " ").split()
            ),
            value_type=field.value_type.value,
            display_value=cls._display_value(field.value),
            source_url=field.source.document_url,
        )

    @staticmethod
    def _display_value(value: Any) -> str:
        if value is None:
            return "Not specified"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
        return str(value)
