import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.candidates import CandidateValueType
from app.models.master import MasterField
from app.repositories.public_recruitments import PublicRecruitmentRepository
from app.schemas.eligibility import (
    ApplicantCategory,
    EligibilityCriterionResult,
    EligibilityEvaluation,
    EligibilityOutcome,
    EligibilityProfile,
)
from app.services.exceptions import ResourceNotFoundError
from app.services.public_recruitments import PublicRecruitmentService

ELIGIBILITY_RULE_VERSION = "V1"


class EligibilityService:
    """Conservative deterministic evaluation over one approved current Master Post."""

    def __init__(self, session: Session) -> None:
        self.repository = PublicRecruitmentRepository(session)

    def evaluate(self, job_id: uuid.UUID, profile: EligibilityProfile) -> EligibilityEvaluation:
        record = self.repository.get_current_active(job_id)
        if record is None:
            raise ResourceNotFoundError("Public job not found")
        fields = {
            PublicRecruitmentService._public_path(record, field): field
            for field in PublicRecruitmentService._visible_fields(record)
        }
        criteria = [
            self._age(fields, profile),
            self._qualification(fields, profile),
            self._domicile(fields, profile),
            self._experience(fields, profile),
        ]
        outcomes = {item.outcome for item in criteria}
        if EligibilityOutcome.NOT_ELIGIBLE in outcomes:
            overall = EligibilityOutcome.NOT_ELIGIBLE
        elif EligibilityOutcome.REVIEW_REQUIRED in outcomes:
            overall = EligibilityOutcome.REVIEW_REQUIRED
        elif EligibilityOutcome.UNKNOWN in outcomes:
            overall = EligibilityOutcome.UNKNOWN
        else:
            overall = EligibilityOutcome.ELIGIBLE
        return EligibilityEvaluation(
            job_id=(record.post.public_id if record.post is not None else record.master.id),
            candidate_key=record.master.candidate_key,
            post_key=record.post.post_key if record.post is not None else None,
            master_revision_number=record.revision.revision_number,
            rule_version=ELIGIBILITY_RULE_VERSION,
            overall_outcome=overall,
            criteria=criteria,
        )

    def _age(
        self, fields: dict[str, MasterField], profile: EligibilityProfile
    ) -> EligibilityCriterionResult:
        minimum = self._first(fields, "age.minimum", "eligibility.minimum_age")
        maximum = self._first(fields, "age.maximum", "eligibility.maximum_age")
        paths = self._paths(minimum, maximum)
        if minimum is None and maximum is None:
            return self._result("AGE", EligibilityOutcome.UNKNOWN, "No approved age rule.", paths)
        cutoff = self._first(fields, "age.reference_date", "eligibility.age_cutoff_date")
        paths = self._paths(minimum, maximum, cutoff)
        if profile.date_of_birth is None:
            return self._result(
                "AGE", EligibilityOutcome.UNKNOWN, "Date of birth was not supplied.", paths
            )
        cutoff_date = self._date(cutoff)
        if cutoff_date is None:
            return self._result(
                "AGE",
                EligibilityOutcome.REVIEW_REQUIRED,
                "The approved age cutoff is missing or not a structured date.",
                paths,
            )
        minimum_value = self._integer(minimum)
        maximum_value = self._integer(maximum)
        if (minimum is not None and minimum_value is None) or (
            maximum is not None and maximum_value is None
        ):
            return self._result(
                "AGE",
                EligibilityOutcome.REVIEW_REQUIRED,
                "An approved age bound is not a structured integer.",
                paths,
            )
        age = self._age_on(profile.date_of_birth, cutoff_date)
        if minimum_value is not None and age < minimum_value:
            return self._result(
                "AGE",
                EligibilityOutcome.NOT_ELIGIBLE,
                f"Age {age} is below the approved minimum of {minimum_value}.",
                paths,
            )
        if maximum_value is not None and age > maximum_value:
            if profile.category in {None, ApplicantCategory.GENERAL}:
                return self._result(
                    "AGE",
                    EligibilityOutcome.NOT_ELIGIBLE,
                    f"Age {age} exceeds the approved maximum of {maximum_value}.",
                    paths,
                )
            relaxation, relaxation_path = self._relaxation(fields, profile.category)
            if relaxation is None:
                return self._result(
                    "AGE",
                    EligibilityOutcome.REVIEW_REQUIRED,
                    "The base maximum is exceeded and no structured relaxation is approved for "
                    f"{profile.category.value}.",
                    paths,
                )
            paths.append(relaxation_path)
            if age > maximum_value + relaxation:
                return self._result(
                    "AGE",
                    EligibilityOutcome.NOT_ELIGIBLE,
                    f"Age {age} exceeds the relaxed maximum of {maximum_value + relaxation}.",
                    paths,
                )
        return self._result(
            "AGE",
            EligibilityOutcome.ELIGIBLE,
            f"Age {age} satisfies the approved structured age bounds.",
            paths,
        )

    def _qualification(
        self, fields: dict[str, MasterField], profile: EligibilityProfile
    ) -> EligibilityCriterionResult:
        requirement = self._first(
            fields, "qualification.minimum", "eligibility.qualification.summary"
        )
        paths = self._paths(requirement)
        if requirement is None:
            return self._result(
                "QUALIFICATION",
                EligibilityOutcome.UNKNOWN,
                "No approved minimum qualification rule.",
                paths,
            )
        if not profile.qualifications:
            return self._result(
                "QUALIFICATION",
                EligibilityOutcome.UNKNOWN,
                "Applicant qualifications were not supplied.",
                paths,
            )
        if requirement.value_type != CandidateValueType.STRING or not isinstance(
            requirement.value, str
        ):
            return self._result(
                "QUALIFICATION",
                EligibilityOutcome.REVIEW_REQUIRED,
                "The approved qualification rule is not deterministically comparable.",
                paths,
            )
        required = self._normalize_text(requirement.value)
        supplied = {self._normalize_text(item) for item in profile.qualifications}
        if required in supplied:
            return self._result(
                "QUALIFICATION",
                EligibilityOutcome.ELIGIBLE,
                "A supplied qualification exactly matches the approved requirement text.",
                paths,
            )
        return self._result(
            "QUALIFICATION",
            EligibilityOutcome.REVIEW_REQUIRED,
            "Qualification equivalence requires human interpretation; no exact match was found.",
            paths,
        )

    def _domicile(
        self, fields: dict[str, MasterField], profile: EligibilityProfile
    ) -> EligibilityCriterionResult:
        requirement = self._first(fields, "domicile.requirement", "eligibility.domicile.summary")
        paths = self._paths(requirement)
        if requirement is None:
            return self._result(
                "DOMICILE",
                EligibilityOutcome.UNKNOWN,
                "No approved domicile rule.",
                paths,
            )
        text = requirement.value if requirement.value_type == CandidateValueType.STRING else None
        recognized = (
            isinstance(text, str)
            and "assam" in text.casefold()
            and any(
                term in text.casefold() for term in ("domicile", "permanent resident", "resident")
            )
        )
        if not recognized:
            return self._result(
                "DOMICILE",
                EligibilityOutcome.REVIEW_REQUIRED,
                "The approved domicile rule is not deterministically comparable.",
                paths,
            )
        if profile.assam_domicile is None:
            return self._result(
                "DOMICILE",
                EligibilityOutcome.UNKNOWN,
                "Assam domicile status was not supplied.",
                paths,
            )
        return self._result(
            "DOMICILE",
            (
                EligibilityOutcome.ELIGIBLE
                if profile.assam_domicile
                else EligibilityOutcome.NOT_ELIGIBLE
            ),
            (
                "Applicant reports satisfying the approved Assam residence requirement."
                if profile.assam_domicile
                else "Applicant reports not satisfying the approved Assam residence requirement."
            ),
            paths,
        )

    def _experience(
        self, fields: dict[str, MasterField], profile: EligibilityProfile
    ) -> EligibilityCriterionResult:
        months = fields.get("experience.minimum_months")
        years = fields.get("experience.minimum_years")
        unstructured = fields.get("experience.minimum")
        requirement = months if months is not None else years if years is not None else unstructured
        paths = self._paths(requirement)
        if requirement is None:
            return self._result(
                "EXPERIENCE",
                EligibilityOutcome.UNKNOWN,
                "No approved minimum experience rule.",
                paths,
            )
        required = self._integer(months)
        if required is None and years is not None:
            value = self._integer(years)
            required = value * 12 if value is not None else None
        if required is None:
            return self._result(
                "EXPERIENCE",
                EligibilityOutcome.REVIEW_REQUIRED,
                "The approved experience rule has no structured month/year value.",
                paths,
            )
        if profile.experience_months is None:
            return self._result(
                "EXPERIENCE",
                EligibilityOutcome.UNKNOWN,
                "Applicant experience was not supplied.",
                paths,
            )
        return self._result(
            "EXPERIENCE",
            (
                EligibilityOutcome.ELIGIBLE
                if profile.experience_months >= required
                else EligibilityOutcome.NOT_ELIGIBLE
            ),
            f"Applicant supplied {profile.experience_months} months; "
            f"approved minimum is {required}.",
            paths,
        )

    @staticmethod
    def _first(fields: dict[str, MasterField], *paths: str) -> MasterField | None:
        return next((fields[path] for path in paths if path in fields), None)

    @staticmethod
    def _integer(field: MasterField | None) -> int | None:
        if field is None or field.value_type != CandidateValueType.INTEGER:
            return None
        return field.value if type(field.value) is int else None

    @staticmethod
    def _date(field: MasterField | None) -> date | None:
        if field is None or field.value_type != CandidateValueType.DATE:
            return None
        try:
            return date.fromisoformat(field.value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _age_on(birth: date, cutoff: date) -> int:
        return cutoff.year - birth.year - ((cutoff.month, cutoff.day) < (birth.month, birth.day))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    @staticmethod
    def _paths(*fields: MasterField | None) -> list[str]:
        return [field.field_path for field in fields if field is not None]

    @staticmethod
    def _result(
        criterion: str,
        outcome: EligibilityOutcome,
        explanation: str,
        paths: list[str],
    ) -> EligibilityCriterionResult:
        return EligibilityCriterionResult(
            criterion=criterion,
            outcome=outcome,
            explanation=explanation,
            master_field_paths=paths,
        )

    @staticmethod
    def _relaxation(
        fields: dict[str, MasterField], category: ApplicantCategory
    ) -> tuple[int | None, str]:
        suffix = category.value.casefold()
        path = f"age.relaxation.{suffix}"
        direct = EligibilityService._integer(fields.get(path))
        if direct is not None:
            return direct, path
        mapping_field = fields.get("eligibility.age_relaxation")
        if mapping_field is None:
            mapping_field = fields.get("age.relaxation")
        if (
            mapping_field is not None
            and mapping_field.value_type == CandidateValueType.JSON
            and isinstance(mapping_field.value, dict)
        ):
            value: Any = mapping_field.value.get(category.value)
            if type(value) is int and value >= 0:
                return value, mapping_field.field_path
        return None, path
