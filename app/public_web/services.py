from dataclasses import dataclass
from datetime import date
from typing import Any

from app.schemas.public_recruitments import (
    PublicAdvertisementSummary,
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
    presentation: dict[str, Any]


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
    official_document_url: str | None


@dataclass(frozen=True)
class PublicAdvertisementSummaryView:
    advertisement: PublicAdvertisementSummary
    sections: tuple[PublicFieldSectionView, ...]
    official_document_url: str | None


class PublicRecruitmentViewService:
    """Format an already-approved public DTO for HTML without domain decisions."""

    _LABELS = {
        "recruitment_name": "Recruitment",
        "name": "Post Name",
        "organization.name": "Organization",
        "organization.unit": "Organization / Unit",
        "vacancies.total": "Total Vacancies",
        "advertisement.vacancies.total": "Advertisement Total Vacancies",
        "application.start_date": "Opening Date",
        "application.end_date": "Closing Date",
        "application.mode": "Application Mode",
        "application.url": "Application Link",
        "application.where_to_apply": "Where to Apply",
        "application.fee": "Application Fee",
        "application.fee_exemptions": "Fee Exemptions",
        "application.payment_mode": "Payment Mode",
        "application.steps": "Official Application Steps",
        "application.documents_required": "Documents Required",
        "qualification.minimum": "Minimum Qualification",
        "qualification.essential": "Essential Qualification",
        "qualification.desirable": "Desirable Qualification",
        "qualification.subject": "Required Subject",
        "qualification.specialisation": "Required Specialisation",
        "qualification.technical": "Technical Qualification",
        "qualification.minimum_percentage": "Minimum Percentage",
        "qualification.minimum_grade": "Minimum Grade",
        "qualification.recognised_institution_requirement": "Recognised Institution Requirement",
        "qualification.registration_or_licence": "Registration / Licence Requirement",
        "experience.minimum_months": "Minimum Experience (Months)",
        "experience.minimum": "Minimum Experience",
        "experience.desirable": "Desirable Experience",
        "age.minimum": "Minimum Age",
        "age.maximum": "Maximum Age",
        "age.reference_date": "Age Reference Date",
        "pay.scale": "Pay Scale",
        "salary.minimum": "Minimum Salary",
        "salary.maximum": "Maximum Salary",
        "domicile.requirement": "Domicile / Residency Requirement",
        "nationality.requirement": "Nationality Requirement",
        "language.requirement": "Language Requirement",
        "selection.process": "Selection Process",
        "selection.phases": "Recruitment Phases",
        "selection.exam_pattern": "Exam Pattern",
        "syllabus.phases": "Official Syllabus",
        "physical.criteria": "Physical Standards",
        "medical.criteria": "Medical Standards",
        "reservation.details": "Reservation Details",
        "eligibility.other": "Other Eligibility Conditions",
        "instructions.important": "Important Instructions",
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
        (
            "selection",
            "Selection Process",
            ("selection.phases", "selection.process", "selection_process"),
        ),
        (
            "exam-syllabus",
            "Exam Pattern / Syllabus",
            ("selection.exam_pattern", "syllabus."),
        ),
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
        return PublicRecruitmentDetailView(
            recruitment=recruitment,
            fields=fields,
            sections=cls._sections(fields),
            official_document_url=cls._official_document_url(fields),
        )

    @classmethod
    def advertisement(
        cls, advertisement: PublicAdvertisementSummary
    ) -> PublicAdvertisementSummaryView:
        fields = tuple(cls._field(field) for field in advertisement.fields)
        return PublicAdvertisementSummaryView(
            advertisement=advertisement,
            sections=cls._sections(fields),
            official_document_url=cls._official_document_url(fields),
        )

    @staticmethod
    def _official_document_url(fields: tuple[PublicFieldView, ...]) -> str | None:
        identity = next((field for field in fields if field.field_path == "recruitment_name"), None)
        if identity is not None:
            return identity.source_url
        return fields[0].source_url if fields else None

    @classmethod
    def _sections(cls, fields: tuple[PublicFieldView, ...]) -> tuple[PublicFieldSectionView, ...]:
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
                PublicFieldSectionView(key="overview", title="Overview", fields=tuple(remaining)),
            )
        return tuple(sections)

    @classmethod
    def _field(cls, field: PublicRecruitmentFieldRead) -> PublicFieldView:
        return PublicFieldView(
            field_path=field.field_path,
            label=cls._LABELS.get(field.field_path, cls._humanize(field.field_path)),
            value_type=field.value_type.value,
            display_value=cls._display_value(field.value, field.value_type.value),
            source_url=field.source.document_url,
            presentation=cls._presentation(field.value, field.field_path, field.value_type.value),
        )

    @classmethod
    def _presentation(cls, value: Any, path: str = "", value_type: str | None = None) -> dict:
        if isinstance(value, list):
            if path == "selection.phases" and value and all(
                isinstance(item, dict) and isinstance(item.get("name"), str) for item in value
            ):
                return {"kind": "phase_list", "items": [
                    {"title": item["name"], "details": cls._presentation({
                        key: cell for key, cell in item.items() if key not in {"name", "sequence"}
                    })} for item in value
                ]}
            if (
                path not in {
                    "selection.phases", "application.steps", "application.documents_required"
                }
                and value
                and all(
                    isinstance(item, dict)
                    and item
                    and all(not isinstance(cell, (dict, list)) for cell in item.values())
                    for item in value
                )
            ):
                keys = list(dict.fromkeys(key for item in value for key in item))
                return {
                    "kind": "structured_table",
                    "headers": [cls._humanize(str(key)) for key in keys],
                    "rows": [[cls._display_value(item.get(key)) for key in keys] for item in value],
                }
            return {
                "kind": "numbered_list"
                if path in {"application.steps", "selection.phases"}
                else "bullet_list",
                "items": [cls._presentation(item) for item in value],
            }
        if isinstance(value, dict):
            return {
                "kind": "key_value_list",
                "items": [
                    {"label": cls._humanize(str(key)), "value": cls._presentation(item)}
                    for key, item in value.items()
                ],
            }
        return {"kind": "paragraph", "text": cls._display_value(value, value_type)}

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
