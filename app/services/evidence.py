import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.discovery import SourceDocumentStatus
from app.models.evidence import CandidateFieldEvidence, Evidence, EvidenceType
from app.repositories.candidates import CandidateFieldRepository
from app.repositories.discovery import SourceDocumentRepository
from app.repositories.evidence import (
    CandidateFieldEvidenceRepository,
    EvidenceRepository,
)
from app.schemas.evidence import EvidenceCreate
from app.services.evidence_values import (
    compute_evidence_hash,
    normalize_evidence_text,
    normalize_optional_evidence_text,
    normalize_source_locator,
)
from app.services.exceptions import DomainConflictError, ResourceNotFoundError


class EvidenceService:
    def __init__(self, session: Session, *, commit: bool = True) -> None:
        self.session = session
        self.commit = commit
        self.documents = SourceDocumentRepository(session)
        self.fields = CandidateFieldRepository(session)
        self.evidence = EvidenceRepository(session)
        self.links = CandidateFieldEvidenceRepository(session)

    def create_evidence(self, data: EvidenceCreate) -> tuple[Evidence, bool]:
        document = self.documents.get(data.source_document_id)
        if document is None:
            raise ResourceNotFoundError("Source document not found")
        if document.status != SourceDocumentStatus.ACTIVE:
            raise DomainConflictError(
                f"Source document in {document.status.value} status cannot create evidence"
            )

        excerpt = normalize_evidence_text(data.excerpt)
        context = normalize_optional_evidence_text(data.context)
        source_locator = normalize_source_locator(data.source_locator)
        evidence_hash = compute_evidence_hash(
            source_document_id=document.id,
            source_document_content_hash=document.content_hash,
            evidence_type=data.evidence_type,
            source_locator=source_locator,
            excerpt=excerpt,
            context=context,
        )
        existing = self.evidence.get_by_identity(document.id, evidence_hash)
        if existing is not None:
            return existing, False

        evidence = Evidence(
            source_document_id=document.id,
            evidence_type=data.evidence_type,
            source_locator=source_locator,
            excerpt=excerpt,
            context=context,
            evidence_hash=evidence_hash,
        )
        self.evidence.add(evidence)
        try:
            self._save()
        except IntegrityError as error:
            self.session.rollback()
            if (
                existing := self.evidence.get_by_identity(document.id, evidence_hash)
            ) is not None:
                return existing, False
            raise DomainConflictError(
                "Evidence conflicted with a concurrent recording; retry"
            ) from error
        return self.get_evidence(evidence.id), True

    def get_evidence(self, evidence_id: uuid.UUID) -> Evidence:
        if (evidence := self.evidence.get(evidence_id)) is None:
            raise ResourceNotFoundError("Evidence not found")
        return evidence

    def list_evidence(
        self,
        *,
        source_document_id: uuid.UUID | None,
        evidence_type: EvidenceType | None,
        offset: int,
        limit: int,
    ) -> list[Evidence]:
        return self.evidence.list(
            source_document_id=source_document_id,
            evidence_type=evidence_type,
            offset=offset,
            limit=limit,
        )

    def link_evidence(
        self, candidate_field_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> tuple[CandidateFieldEvidence, bool]:
        field = self.fields.get(candidate_field_id)
        if field is None:
            raise ResourceNotFoundError("Candidate field not found")
        evidence = self.get_evidence(evidence_id)
        if field.source_document_id != evidence.source_document_id:
            raise DomainConflictError(
                "Candidate field and evidence must reference the same source document"
            )
        if (existing := self.links.get_link(field.id, evidence.id)) is not None:
            return existing, False

        link = CandidateFieldEvidence(
            candidate_field_id=field.id,
            evidence_id=evidence.id,
            source_document_id=field.source_document_id,
        )
        self.links.add(link)
        try:
            self._save()
        except IntegrityError as error:
            self.session.rollback()
            if (existing := self.links.get_link(field.id, evidence.id)) is not None:
                return existing, False
            raise DomainConflictError(
                "Evidence link conflicted with a concurrent recording; retry"
            ) from error
        return link, True

    def list_field_evidence(self, candidate_field_id: uuid.UUID) -> list[Evidence]:
        if self.fields.get(candidate_field_id) is None:
            raise ResourceNotFoundError("Candidate field not found")
        return self.links.list_evidence_for_field(candidate_field_id)

    def _save(self) -> None:
        self.session.commit() if self.commit else self.session.flush()
