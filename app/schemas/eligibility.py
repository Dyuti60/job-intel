import enum
import uuid
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class EligibilitySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicantCategory(enum.StrEnum):
    GENERAL = "GENERAL"
    OBC_MOBC = "OBC_MOBC"
    SC = "SC"
    ST_P = "ST_P"
    ST_H = "ST_H"
    EWS = "EWS"
    PWBD = "PWBD"


class EligibilityOutcome(enum.StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    UNKNOWN = "UNKNOWN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


QualificationText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class EligibilityProfile(EligibilitySchema):
    date_of_birth: date | None = None
    category: ApplicantCategory | None = None
    assam_domicile: bool | None = None
    qualifications: list[QualificationText] = Field(default_factory=list, max_length=50)
    experience_months: int | None = Field(default=None, ge=0, le=1_200)


class EligibilityCriterionResult(EligibilitySchema):
    criterion: str
    outcome: EligibilityOutcome
    explanation: str
    master_field_paths: list[str]


class EligibilityEvaluation(EligibilitySchema):
    job_id: uuid.UUID
    candidate_key: str
    post_key: str | None
    master_revision_number: int
    rule_version: str
    overall_outcome: EligibilityOutcome
    criteria: list[EligibilityCriterionResult]
