import copy
import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidates import CandidateStatus
from app.models.discovery import SourceDocumentStatus
from app.models.source_registry import SourceClass
from app.models.verification import (
    EvidenceAssessmentType,
    FieldVerification,
    FieldVerificationOutcome,
    FieldVerificationStatus,
    VerificationEvidenceAssessment,
    VerificationReasonCode,
    VerificationRun,
    VerificationRunStatus,
    VerificationTriggerType,
)
from app.repositories.candidates import (
    CandidateFieldRepository,
    CandidateRevisionRepository,
)
from app.repositories.evidence import EvidenceRepository
from app.repositories.verification import (
    FieldVerificationRepository,
    VerificationAssessmentRepository,
    VerificationRunRepository,
)
from app.schemas.verification import (
    VerificationEvidenceAssessmentCreate,
    VerificationRunComplete,
    VerificationRunCreate,
)
from app.services.candidate_values import compute_revision_hash
from app.services.evidence_values import compute_evidence_hash
from app.services.exceptions import DomainConflictError, ResourceNotFoundError


class VerificationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.runs = VerificationRunRepository(session)
        self.field_verifications = FieldVerificationRepository(session)
        self.assessments = VerificationAssessmentRepository(session)
        self.revisions = CandidateRevisionRepository(session)
        self.fields = CandidateFieldRepository(session)
        self.evidence = EvidenceRepository(session)

    def create_run(self, data: VerificationRunCreate) -> VerificationRun:
        revision = self.revisions.get(data.candidate_revision_id)
        if revision is None:
            raise ResourceNotFoundError("Candidate revision not found")
        candidate = revision.recruitment_candidate
        if candidate.status == CandidateStatus.DISCARDED:
            raise DomainConflictError("Discarded candidates cannot be verified")
        if candidate.status != CandidateStatus.READY_FOR_VERIFICATION:
            raise DomainConflictError("Candidate is not ready for verification")
        if not revision.fields:
            raise DomainConflictError("Candidate revision has no fields to verify")
        if self._computed_revision_hash(revision) != revision.revision_hash:
            raise DomainConflictError("Candidate revision integrity check failed")

        run = VerificationRun(
            candidate_revision_id=revision.id,
            candidate_revision_hash_snapshot=revision.revision_hash,
            status=VerificationRunStatus.PENDING,
            trigger_type=data.trigger_type,
            fields_total=len(revision.fields),
            fields_confirmed=0,
            fields_conflicted=0,
            fields_insufficient=0,
            fields_not_applicable=0,
        )
        self.runs.add(run)
        self.session.commit()
        return self.get_run(run.id)

    def get_run(self, run_id: uuid.UUID) -> VerificationRun:
        if (run := self.runs.get(run_id)) is None:
            raise ResourceNotFoundError("Verification run not found")
        return run

    def list_runs(
        self,
        *,
        candidate_revision_id: uuid.UUID | None,
        candidate_id: uuid.UUID | None,
        status: VerificationRunStatus | None,
        trigger_type: VerificationTriggerType | None,
        offset: int,
        limit: int,
    ) -> list[VerificationRun]:
        return self.runs.list(
            candidate_revision_id=candidate_revision_id,
            candidate_id=candidate_id,
            status=status,
            trigger_type=trigger_type,
            offset=offset,
            limit=limit,
        )

    def start_run(self, run_id: uuid.UUID) -> VerificationRun:
        run = self.get_run(run_id)
        if run.status != VerificationRunStatus.PENDING:
            raise DomainConflictError(
                f"Cannot start verification run in {run.status.value} status"
            )
        self._validate_revision_snapshot(run)
        run.status = VerificationRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        self.session.commit()
        return self.get_run(run.id)

    def complete_run(
        self, run_id: uuid.UUID, data: VerificationRunComplete
    ) -> VerificationRun:
        run = self.get_run(run_id)
        if run.status != VerificationRunStatus.RUNNING:
            raise DomainConflictError(
                f"Cannot complete verification run in {run.status.value} status"
            )
        self._validate_revision_snapshot(run)
        finalized = self.field_verifications.finalized_count(run.id)
        if (
            data.status == VerificationRunStatus.COMPLETED
            and finalized != run.fields_total
        ):
            raise DomainConflictError(
                "COMPLETED requires a finalized verification for every candidate field"
            )
        if data.status == VerificationRunStatus.PARTIAL and not (
            0 < finalized < run.fields_total
        ):
            raise DomainConflictError(
                "PARTIAL requires at least one but not all fields to be finalized"
            )

        run.status = data.status
        run.completed_at = datetime.now(UTC)
        if data.status == VerificationRunStatus.COMPLETED:
            run.error_code = None
            run.error_message = None
        else:
            run.error_code = data.error_code
            run.error_message = data.error_message
        self.session.commit()
        return self.get_run(run.id)

    def create_field_verification(
        self, run_id: uuid.UUID, candidate_field_id: uuid.UUID
    ) -> tuple[FieldVerification, bool]:
        run = self.get_run(run_id)
        if run.status != VerificationRunStatus.RUNNING:
            raise DomainConflictError(
                f"Verification run in {run.status.value} status cannot receive fields"
            )
        self._validate_revision_snapshot(run)
        field = self.fields.get(candidate_field_id)
        if field is None:
            raise ResourceNotFoundError("Candidate field not found")
        if field.candidate_revision_id != run.candidate_revision_id:
            raise DomainConflictError(
                "Candidate field does not belong to the verification run revision"
            )
        existing = self.field_verifications.get_for_run_field(run.id, field.id)
        if existing is not None:
            return self.get_field_verification(existing.id), False

        verification = FieldVerification(
            verification_run_id=run.id,
            candidate_field_id=field.id,
            candidate_field_path_snapshot=field.field_path,
            candidate_field_value_snapshot=copy.deepcopy(field.value),
            candidate_field_type_snapshot=field.value_type,
            status=FieldVerificationStatus.PENDING,
            authoritative_support_count=0,
            official_support_count=0,
            secondary_support_count=0,
            authoritative_conflict_count=0,
            official_conflict_count=0,
            secondary_conflict_count=0,
            evidence_count=0,
        )
        self.field_verifications.add(verification)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            existing = self.field_verifications.get_for_run_field(run.id, field.id)
            if existing is not None:
                return self.get_field_verification(existing.id), False
            raise DomainConflictError(
                "Field verification conflicted with concurrent creation; retry"
            ) from error
        return self.get_field_verification(verification.id), True

    def get_field_verification(
        self, verification_id: uuid.UUID
    ) -> FieldVerification:
        verification = self.field_verifications.get(verification_id)
        if verification is None:
            raise ResourceNotFoundError("Field verification not found")
        return verification

    def list_field_verifications(self, run_id: uuid.UUID) -> list[FieldVerification]:
        self.get_run(run_id)
        return self.field_verifications.list_for_run(run_id)

    def add_assessment(
        self,
        verification_id: uuid.UUID,
        data: VerificationEvidenceAssessmentCreate,
    ) -> tuple[FieldVerification, bool]:
        verification = self.get_field_verification(verification_id)
        existing = self.assessments.get_for_field_evidence(
            verification.id, data.evidence_id
        )
        if existing is not None:
            if self._assessment_matches(existing, data):
                return verification, False
            raise DomainConflictError(
                "Evidence already has a different assessment for this field verification"
            )
        if verification.status != FieldVerificationStatus.PENDING:
            raise DomainConflictError("Finalized field verification is immutable")
        run = self.get_run(verification.verification_run_id)
        if run.status != VerificationRunStatus.RUNNING:
            raise DomainConflictError(
                f"Verification run in {run.status.value} status cannot receive assessments"
            )
        self._validate_revision_snapshot(run)

        evidence = self.evidence.get(data.evidence_id)
        if evidence is None:
            raise ResourceNotFoundError("Evidence not found")
        document = evidence.source_document
        if document.status != SourceDocumentStatus.ACTIVE:
            raise DomainConflictError(
                f"Evidence source document is {document.status.value}"
            )
        if document.source_endpoint is None:
            raise DomainConflictError("Evidence source endpoint provenance is unavailable")
        expected_hash = compute_evidence_hash(
            source_document_id=document.id,
            source_document_content_hash=document.content_hash,
            evidence_type=evidence.evidence_type,
            source_locator=evidence.source_locator,
            excerpt=evidence.excerpt,
            context=evidence.context,
        )
        if evidence.evidence_hash != expected_hash:
            raise DomainConflictError("Evidence integrity hash is invalid")
        self._validate_asserted_value(verification, data)

        assessment = VerificationEvidenceAssessment(
            field_verification_id=verification.id,
            evidence_id=evidence.id,
            assessment=data.assessment,
            asserted_value=copy.deepcopy(data.asserted_value),
            asserted_value_type=data.asserted_value_type,
            source_class_snapshot=document.source_endpoint.source_class,
            assessment_note=data.assessment_note,
        )
        self.assessments.add(assessment)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            existing = self.assessments.get_for_field_evidence(
                verification.id, evidence.id
            )
            if existing is not None and self._assessment_matches(existing, data):
                return self.get_field_verification(verification.id), False
            raise DomainConflictError(
                "Evidence assessment conflicted with concurrent creation; retry"
            ) from error
        return self.get_field_verification(verification.id), True

    def finalize_field_verification(
        self, verification_id: uuid.UUID, *, not_applicable: bool
    ) -> tuple[FieldVerification, bool]:
        verification = self.get_field_verification(verification_id)
        if verification.status == FieldVerificationStatus.FINALIZED:
            was_not_applicable = (
                verification.outcome == FieldVerificationOutcome.NOT_APPLICABLE
            )
            if was_not_applicable == not_applicable:
                return verification, False
            raise DomainConflictError("Finalized field verification is immutable")
        run = self.get_run(verification.verification_run_id)
        if run.status != VerificationRunStatus.RUNNING:
            raise DomainConflictError(
                f"Verification run in {run.status.value} status cannot finalize fields"
            )
        self._validate_revision_snapshot(run)

        counts = Counter(
            (assessment.source_class_snapshot, assessment.assessment)
            for assessment in verification.assessments
        )
        verification.authoritative_support_count = counts[
            (SourceClass.AUTHORITATIVE_OFFICIAL, EvidenceAssessmentType.SUPPORTS)
        ]
        verification.official_support_count = counts[
            (SourceClass.OFFICIAL_SUPPORTING, EvidenceAssessmentType.SUPPORTS)
        ]
        verification.secondary_support_count = counts[
            (SourceClass.SECONDARY_DISCOVERY_ONLY, EvidenceAssessmentType.SUPPORTS)
        ]
        verification.authoritative_conflict_count = counts[
            (SourceClass.AUTHORITATIVE_OFFICIAL, EvidenceAssessmentType.CONTRADICTS)
        ]
        verification.official_conflict_count = counts[
            (SourceClass.OFFICIAL_SUPPORTING, EvidenceAssessmentType.CONTRADICTS)
        ]
        verification.secondary_conflict_count = counts[
            (SourceClass.SECONDARY_DISCOVERY_ONLY, EvidenceAssessmentType.CONTRADICTS)
        ]
        verification.evidence_count = len(verification.assessments)
        outcome, reason = self._determine_outcome(verification, not_applicable)
        verification.outcome = outcome
        verification.reason_code = reason
        verification.finding_summary = self._finding_summary(verification)
        verification.status = FieldVerificationStatus.FINALIZED
        verification.finalized_at = datetime.now(UTC)
        self._increment_run_counter(run, outcome)
        self.session.commit()
        return self.get_field_verification(verification.id), True

    def _validate_revision_snapshot(self, run: VerificationRun) -> None:
        revision = self.revisions.get(run.candidate_revision_id)
        if revision is None:
            raise DomainConflictError("Verification run revision is unavailable")
        if revision.recruitment_candidate.status != CandidateStatus.READY_FOR_VERIFICATION:
            raise DomainConflictError("Candidate is no longer ready for verification")
        if (
            revision.revision_hash != run.candidate_revision_hash_snapshot
            or self._computed_revision_hash(revision)
            != run.candidate_revision_hash_snapshot
        ):
            raise DomainConflictError("Candidate revision hash snapshot mismatch")

    @staticmethod
    def _computed_revision_hash(revision) -> str:
        return compute_revision_hash(
            source_document_id=revision.source_document_id,
            source_document_content_hash=revision.source_document.content_hash,
            fields=[
                (field.field_path, field.value_type, field.value)
                for field in revision.fields
            ],
        )

    @staticmethod
    def _validate_asserted_value(
        verification: FieldVerification,
        data: VerificationEvidenceAssessmentCreate,
    ) -> None:
        if data.asserted_value_type is None:
            return
        same_value = (
            data.asserted_value_type == verification.candidate_field_type_snapshot
            and data.asserted_value == verification.candidate_field_value_snapshot
        )
        if data.assessment == EvidenceAssessmentType.SUPPORTS and not same_value:
            raise DomainConflictError(
                "SUPPORTS asserted value must equal the candidate field snapshot"
            )
        if data.assessment == EvidenceAssessmentType.CONTRADICTS and same_value:
            raise DomainConflictError(
                "CONTRADICTS asserted value must differ from the candidate field snapshot"
            )

    @staticmethod
    def _assessment_matches(
        existing: VerificationEvidenceAssessment,
        data: VerificationEvidenceAssessmentCreate,
    ) -> bool:
        return (
            existing.assessment == data.assessment
            and existing.asserted_value_type == data.asserted_value_type
            and existing.asserted_value == data.asserted_value
            and existing.assessment_note == data.assessment_note
        )

    @staticmethod
    def _determine_outcome(
        verification: FieldVerification, not_applicable: bool
    ) -> tuple[FieldVerificationOutcome, VerificationReasonCode]:
        if not_applicable:
            return (
                FieldVerificationOutcome.NOT_APPLICABLE,
                VerificationReasonCode.MANUALLY_MARKED_NOT_APPLICABLE,
            )
        if verification.authoritative_conflict_count:
            return (
                FieldVerificationOutcome.CONFLICT,
                VerificationReasonCode.AUTHORITATIVE_CONFLICT,
            )
        if verification.authoritative_support_count:
            return (
                FieldVerificationOutcome.CONFIRMED,
                VerificationReasonCode.AUTHORITATIVE_SUPPORT,
            )

        support_total = (
            verification.official_support_count
            + verification.secondary_support_count
        )
        conflict_total = (
            verification.official_conflict_count
            + verification.secondary_conflict_count
        )
        if support_total and conflict_total:
            return (
                FieldVerificationOutcome.CONFLICT,
                VerificationReasonCode.SOURCE_CONFLICT,
            )
        if verification.evidence_count == 0:
            return (
                FieldVerificationOutcome.INSUFFICIENT_EVIDENCE,
                VerificationReasonCode.NO_EVIDENCE,
            )
        if verification.secondary_support_count and not (
            verification.official_support_count or conflict_total
        ):
            return (
                FieldVerificationOutcome.INSUFFICIENT_EVIDENCE,
                VerificationReasonCode.ONLY_SECONDARY_EVIDENCE,
            )
        return (
            FieldVerificationOutcome.INSUFFICIENT_EVIDENCE,
            VerificationReasonCode.INSUFFICIENT_SUPPORT,
        )

    @staticmethod
    def _finding_summary(verification: FieldVerification) -> str:
        return (
            f"{verification.outcome.value}: {verification.reason_code.value}; "
            f"authoritative support={verification.authoritative_support_count}, "
            f"official support={verification.official_support_count}, "
            f"secondary support={verification.secondary_support_count}, "
            f"authoritative conflicts={verification.authoritative_conflict_count}, "
            f"official conflicts={verification.official_conflict_count}, "
            f"secondary conflicts={verification.secondary_conflict_count}, "
            f"evidence evaluated={verification.evidence_count}."
        )

    @staticmethod
    def _increment_run_counter(
        run: VerificationRun, outcome: FieldVerificationOutcome
    ) -> None:
        attribute = {
            FieldVerificationOutcome.CONFIRMED: "fields_confirmed",
            FieldVerificationOutcome.CONFLICT: "fields_conflicted",
            FieldVerificationOutcome.INSUFFICIENT_EVIDENCE: "fields_insufficient",
            FieldVerificationOutcome.NOT_APPLICABLE: "fields_not_applicable",
        }[outcome]
        setattr(run, attribute, getattr(run, attribute) + 1)
