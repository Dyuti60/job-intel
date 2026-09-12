import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.evidence import CandidateFieldEvidence, Evidence, EvidenceType


class EvidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, evidence: Evidence) -> None:
        self.session.add(evidence)

    def get(self, evidence_id: uuid.UUID) -> Evidence | None:
        return self.session.get(Evidence, evidence_id)

    def get_by_identity(
        self, source_document_id: uuid.UUID, evidence_hash: str
    ) -> Evidence | None:
        return self.session.scalar(
            select(Evidence).where(
                Evidence.source_document_id == source_document_id,
                Evidence.evidence_hash == evidence_hash,
            )
        )

    def list(
        self,
        *,
        source_document_id: uuid.UUID | None = None,
        evidence_type: EvidenceType | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Evidence]:
        statement: Select[tuple[Evidence]] = select(Evidence).order_by(
            Evidence.created_at, Evidence.id
        )
        if source_document_id is not None:
            statement = statement.where(
                Evidence.source_document_id == source_document_id
            )
        if evidence_type is not None:
            statement = statement.where(Evidence.evidence_type == evidence_type)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


class CandidateFieldEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, link: CandidateFieldEvidence) -> None:
        self.session.add(link)

    def get_link(
        self, candidate_field_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> CandidateFieldEvidence | None:
        return self.session.scalar(
            select(CandidateFieldEvidence).where(
                CandidateFieldEvidence.candidate_field_id == candidate_field_id,
                CandidateFieldEvidence.evidence_id == evidence_id,
            )
        )

    def list_evidence_for_field(self, candidate_field_id: uuid.UUID) -> list[Evidence]:
        return list(
            self.session.scalars(
                select(Evidence)
                .join(
                    CandidateFieldEvidence,
                    CandidateFieldEvidence.evidence_id == Evidence.id,
                )
                .where(
                    CandidateFieldEvidence.candidate_field_id == candidate_field_id
                )
                .order_by(Evidence.created_at, Evidence.id)
            )
        )
