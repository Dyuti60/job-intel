import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.candidates import CandidateValueType
from app.models.master import (
    MasterChangeType,
    MasterFieldValueOrigin,
    PublicationPath,
    PublicationResult,
    RecruitmentMasterStatus,
)


class MasterSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class MasterPublishRequest(MasterSchema):
    revision_confidence_assessment_id: uuid.UUID


class MasterFieldRead(MasterSchema):
    id: uuid.UUID
    master_revision_id: uuid.UUID
    field_path: str
    value_type: CandidateValueType
    value: Any
    source_candidate_field_id: uuid.UUID
    review_decision_id: uuid.UUID | None
    value_origin: MasterFieldValueOrigin
    created_at: datetime


class MasterPostFactRead(MasterSchema):
    id: uuid.UUID
    master_post_id: uuid.UUID
    master_field_id: uuid.UUID
    source_post_fact_id: uuid.UUID
    fact_key: str
    created_at: datetime


class MasterPostRead(MasterSchema):
    id: uuid.UUID
    public_id: uuid.UUID
    master_revision_id: uuid.UUID
    source_recruitment_post_id: uuid.UUID
    post_key: str
    ordinal: int
    name: str
    normalized_name: str
    facts: list[MasterPostFactRead]
    created_at: datetime


class MasterRevisionSummary(MasterSchema):
    id: uuid.UUID
    recruitment_master_id: uuid.UUID
    revision_number: int
    projection_hash: str
    display_name: str
    source_candidate_revision_id: uuid.UUID
    verification_run_id: uuid.UUID
    revision_confidence_assessment_id: uuid.UUID
    review_case_id: uuid.UUID | None
    publication_path: PublicationPath
    published_at: datetime
    verified_at: datetime
    created_at: datetime


class MasterRevisionRead(MasterRevisionSummary):
    fields: list[MasterFieldRead]
    posts: list[MasterPostRead]


class RecruitmentMasterSummary(MasterSchema):
    id: uuid.UUID
    recruiting_authority_id: uuid.UUID
    candidate_key: str
    display_name: str
    status: RecruitmentMasterStatus
    current_revision_id: uuid.UUID
    first_published_at: datetime
    last_published_at: datetime
    last_verified_at: datetime
    created_at: datetime
    updated_at: datetime


class RecruitmentMasterRead(RecruitmentMasterSummary):
    current_revision: MasterRevisionRead


class MasterPublicationEventRead(MasterSchema):
    id: uuid.UUID
    recruitment_master_id: uuid.UUID
    master_revision_id: uuid.UUID
    source_candidate_revision_id: uuid.UUID
    verification_run_id: uuid.UUID
    revision_confidence_assessment_id: uuid.UUID
    review_case_id: uuid.UUID | None
    publication_path: PublicationPath
    result: PublicationResult
    published_or_verified_at: datetime
    created_at: datetime


class MasterChangeRead(MasterSchema):
    id: uuid.UUID
    recruitment_master_id: uuid.UUID
    from_master_revision_id: uuid.UUID | None
    to_master_revision_id: uuid.UUID
    field_path: str
    change_type: MasterChangeType
    old_value_type: CandidateValueType | None
    old_value: Any
    new_value_type: CandidateValueType | None
    new_value: Any
    source_candidate_field_id: uuid.UUID
    review_decision_id: uuid.UUID | None
    created_at: datetime


class MasterPublishResult(MasterSchema):
    master: RecruitmentMasterRead
    master_revision: MasterRevisionRead
    publication_event: MasterPublicationEventRead
    revision_created: bool
