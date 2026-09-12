import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidates import (
    CandidateField,
    CandidateStatus,
    RecruitmentCandidate,
    RecruitmentCandidateRevision,
)
from app.models.discovery import SourceDocumentStatus
from app.models.source_registry import AuthorityStatus
from app.repositories.candidates import (
    CandidateFieldRepository,
    CandidateRevisionRepository,
    RecruitmentCandidateRepository,
)
from app.repositories.discovery import SourceDocumentRepository
from app.repositories.source_registry import RecruitingAuthorityRepository
from app.schemas.candidates import (
    RecruitmentCandidateCreate,
    RecruitmentCandidateRevisionCreate,
)
from app.services.candidate_values import compute_revision_hash
from app.services.exceptions import (
    DomainConflictError,
    DuplicateResourceError,
    ResourceNotFoundError,
)


class CandidateService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.authorities = RecruitingAuthorityRepository(session)
        self.candidates = RecruitmentCandidateRepository(session)
        self.revisions = CandidateRevisionRepository(session)
        self.fields = CandidateFieldRepository(session)
        self.documents = SourceDocumentRepository(session)

    def create_candidate(
        self, data: RecruitmentCandidateCreate
    ) -> RecruitmentCandidate:
        authority = self.authorities.get(data.recruiting_authority_id)
        if authority is None:
            raise ResourceNotFoundError("Recruiting authority not found")
        if authority.status != AuthorityStatus.ACTIVE:
            raise DomainConflictError("Recruiting authority is not active")
        if (
            self.candidates.get_by_identity(
                data.recruiting_authority_id, data.candidate_key
            )
            is not None
        ):
            raise DuplicateResourceError(
                f"Candidate key '{data.candidate_key}' already exists for this authority"
            )

        candidate = RecruitmentCandidate(
            recruiting_authority_id=data.recruiting_authority_id,
            candidate_key=data.candidate_key,
            display_name=data.display_name,
            status=CandidateStatus.DRAFT,
        )
        self.candidates.add(candidate)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise DuplicateResourceError(
                f"Candidate key '{data.candidate_key}' already exists for this authority"
            ) from error
        return self.get_candidate(candidate.id)

    def get_candidate(self, candidate_id: uuid.UUID) -> RecruitmentCandidate:
        if (candidate := self.candidates.get(candidate_id)) is None:
            raise ResourceNotFoundError("Recruitment candidate not found")
        return candidate

    def list_candidates(
        self,
        *,
        recruiting_authority_id: uuid.UUID | None,
        status: CandidateStatus | None,
        offset: int,
        limit: int,
    ) -> list[RecruitmentCandidate]:
        return self.candidates.list(
            recruiting_authority_id=recruiting_authority_id,
            status=status,
            offset=offset,
            limit=limit,
        )

    def update_candidate_status(
        self, candidate_id: uuid.UUID, target_status: CandidateStatus
    ) -> RecruitmentCandidate:
        candidate = self.get_candidate(candidate_id)
        if candidate.status == target_status:
            return candidate
        allowed = {
            CandidateStatus.READY_FOR_VERIFICATION,
            CandidateStatus.DISCARDED,
        }
        if candidate.status != CandidateStatus.DRAFT or target_status not in allowed:
            raise DomainConflictError(
                f"Cannot transition candidate from {candidate.status.value} "
                f"to {target_status.value}"
            )
        if (
            target_status == CandidateStatus.READY_FOR_VERIFICATION
            and not self.revisions.has_revision(candidate.id)
        ):
            raise DomainConflictError(
                "Candidate requires at least one revision before readiness"
            )
        candidate.status = target_status
        self.session.commit()
        return self.get_candidate(candidate.id)

    def create_revision(
        self,
        candidate_id: uuid.UUID,
        data: RecruitmentCandidateRevisionCreate,
    ) -> tuple[RecruitmentCandidateRevision, bool]:
        candidate = self.get_candidate(candidate_id)
        if candidate.status == CandidateStatus.DISCARDED:
            raise DomainConflictError("Discarded candidates cannot receive new revisions")
        document = self.documents.get(data.source_document_id)
        if document is None:
            raise ResourceNotFoundError("Source document not found")
        if document.status != SourceDocumentStatus.ACTIVE:
            raise DomainConflictError(
                f"Source document in {document.status.value} status cannot create a revision"
            )
        if (
            document.source_endpoint.recruiting_authority_id
            != candidate.recruiting_authority_id
        ):
            raise DomainConflictError(
                "Candidate authority does not match source document authority"
            )

        revision_hash = compute_revision_hash(
            source_document_id=document.id,
            source_document_content_hash=document.content_hash,
            fields=[
                (field.field_path, field.value_type, field.value)
                for field in data.fields
            ],
        )
        existing = self.revisions.get_by_hash(candidate.id, revision_hash)
        if existing is not None:
            return existing, False

        revision = RecruitmentCandidateRevision(
            recruitment_candidate_id=candidate.id,
            source_document_id=document.id,
            revision_number=self.revisions.next_revision_number(candidate.id),
            revision_hash=revision_hash,
            extraction_method=data.extraction_method,
            extraction_note=data.extraction_note,
        )
        revision.fields = [
            CandidateField(
                source_document_id=document.id,
                field_path=field.field_path,
                value_type=field.value_type,
                value=field.value,
                raw_value=field.raw_value,
                source_locator=field.source_locator,
            )
            for field in sorted(data.fields, key=lambda item: item.field_path)
        ]
        self.revisions.add(revision)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            if (
                existing := self.revisions.get_by_hash(candidate.id, revision_hash)
            ) is not None:
                return existing, False
            raise DomainConflictError(
                "Candidate revision conflicted with a concurrent revision; retry"
            ) from error
        return self.get_revision(revision.id), True

    def get_revision(self, revision_id: uuid.UUID) -> RecruitmentCandidateRevision:
        if (revision := self.revisions.get(revision_id)) is None:
            raise ResourceNotFoundError("Candidate revision not found")
        return revision

    def list_revisions(
        self, candidate_id: uuid.UUID
    ) -> list[RecruitmentCandidateRevision]:
        self.get_candidate(candidate_id)
        return self.revisions.list_for_candidate(candidate_id)

    def list_fields(self, revision_id: uuid.UUID) -> list[CandidateField]:
        self.get_revision(revision_id)
        return self.fields.list_for_revision(revision_id)
