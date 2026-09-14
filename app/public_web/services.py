from dataclasses import dataclass
from datetime import date
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
class PublicFieldSectionView:
    key: str
    title: str
    fields: tuple[PublicFieldView, ...]


@dataclass(frozen=True)
class PublicRecruitmentDetailView:
    recruitment: PublicRecruitmentDetail
    fields: tuple[PublicFieldView, ...]
    sections: tuple[PublicFieldSectionView, ...]


class PublicRecruitmentViewService:
    """Format an already-approved public DTO for HTML without domain decisions."""

    _LABELS = {
        "recruitment_name": "Recruitment",
        "name": "Post Name",
        "organization.name": "Organization",
        "organization.unit": "Organization / Unit",
        "vacancies.total": "Total Vacancies",
        "application.start_date": "Opening Date",
        "application.end_date": "Closing Date",
        "application.mode": "Application Mode",
        "application.url": "Application Link",
        "qualification.minimum": "Minimum Qualification",
        "experience.minimum_months": "Minimum Experience (Months)",
        "age.minimum": "Minimum Age",
        "age.maximum": "Maximum Age",
        "age.reference_date": "Age Reference Date",
        "pay.scale": "Pay Scale",
        "salary.minimum": "Minimum Salary",
        "salary.maximum": "Maximum Salary",
        "domicile.requirement": "Domicile Requirement",
        "selection.process": "Selection Process",
    }
    _SECTIONS = (
        ("vacancies", "Vacancies", ("vacancies.", "category_vacancies.")),
        (
            "important-dates",
            "Important Dates",
            ("application.start_date", "application.end_date", "important_dates.", "exam.date"),
        ),
        ("age", "Age Criteria", ("age.", "age_relaxation.")),
        (
            "qualification",
            "Educational Qualification",
            ("qualification.", "education."),
        ),
        ("experience", "Experience", ("experience.",)),
        ("salary", "Salary / Pay Scale", ("salary.", "pay.", "remuneration.")),
        (
            "eligibility",
            "Eligibility",
            ("eligibility.", "domicile.", "nationality.", "citizenship."),
        ),
        (
            "application",
            "Application Details",
            ("application.", "application_fee.", "fee.", "how_to_apply"),
        ),
        ("selection", "Selection Process", ("selection.", "selection_process")),
        (
            "reservation",
            "Reservation / Category",
            ("reservation.", "category.", "categories."),
        ),
        (
            "physical-medical",
            "Physical / Medical Criteria",
            ("physical.", "medical."),
        ),
        (
            "important-notes",
            "Important Notes",
            ("important_notes", "notes.", "description.", "instructions."),
        ),
    )

    @classmethod
    def detail(cls, recruitment: PublicRecruitmentDetail) -> PublicRecruitmentDetailView:
        fields = tuple(cls._field(field) for field in recruitment.fields)
        remaining = list(fields)
        sections: list[PublicFieldSectionView] = []
        for key, title, prefixes in cls._SECTIONS:
            selected = tuple(
                field
                for field in remaining
                if any(
                    field.field_path == prefix or field.field_path.startswith(prefix)
                    for prefix in prefixes
                )
            )
            if selected:
                sections.append(PublicFieldSectionView(key=key, title=title, fields=selected))
                selected_paths = {field.field_path for field in selected}
                remaining = [field for field in remaining if field.field_path not in selected_paths]
        if remaining:
            sections.insert(
                0,
                PublicFieldSectionView(
                    key="overview", title="Overview", fields=tuple(remaining)
                ),
            )
        return PublicRecruitmentDetailView(
            recruitment=recruitment,
            fields=fields,
            sections=tuple(sections),
        )

    @classmethod
    def _field(cls, field: PublicRecruitmentFieldRead) -> PublicFieldView:
        return PublicFieldView(
            field_path=field.field_path,
            label=cls._LABELS.get(field.field_path, cls._humanize(field.field_path)),
            value_type=field.value_type.value,
            display_value=cls._display_value(field.value, field.value_type.value),
            source_url=field.source.document_url,
        )

    @staticmethod
    def _humanize(path: str) -> str:
        words = path.replace(".", " ").replace("_", " ").split()
        return " ".join(part.capitalize() for part in words)

    @classmethod
    def _display_value(cls, value: Any, value_type: str | None = None) -> str:
        if value is None:
            return "Not specified"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if value_type == "DATE" and isinstance(value, str):
            try:
                return date.fromisoformat(value).strftime("%d %B %Y").lstrip("0")
            except ValueError:
                pass
        if isinstance(value, str):
            return " ".join(value.split())
        if isinstance(value, list):
            return "\n".join(f"• {cls._display_value(item)}" for item in value)
        if isinstance(value, dict):
            return "\n".join(
                f"{cls._humanize(str(key))}: {cls._display_value(value[key])}"
                for key in sorted(value, key=str)
            )
        if isinstance(value, date):
            return value.strftime("%d %B %Y").lstrip("0")
        return str(value)
