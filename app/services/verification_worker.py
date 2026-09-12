import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.candidates import (
    CandidateField,
    CandidateStatus,
    RecruitmentCandidate,
    RecruitmentCandidateRevision,
)
from app.models.confidence import ConfidencePolicyVersion, RevisionConfidenceAssessment
from app.models.review import ReviewCase, ReviewCaseOutcome, ReviewCaseStatus
from app.models.source_registry import RecruitingAuthority
from app.models.verification import (
    VerificationRun,
    VerificationRunStatus,
    VerificationTriggerType,
)
from app.repositories.evidence import CandidateFieldEvidenceRepository
from app.schemas.verification import (
    VerificationEvidenceAssessmentCreate,
    VerificationRunComplete,
    VerificationRunCreate,
)
from app.services.candidate_field_evidence_verifier import CandidateFieldEvidenceVerifier
from app.services.candidates import CandidateService
from app.services.confidence import ConfidenceService
from app.services.review import ReviewService
from app.services.verification import VerificationService


@dataclass(frozen=True)
class VerificationWorkerItemResult:
    candidate_revision_id: uuid.UUID
    verification_run_id: uuid.UUID
    confidence_assessment_id: uuid.UUID
    review_case_id: uuid.UUID | None
    score: int | None
    fields_confirmed: int
    fields_conflicted: int
    fields_insufficient: int
    fields_not_applicable: int
    review_required: bool


@dataclass
class VerificationWorkerSummary:
    authority: str | None
    dry_run: bool
    revisions_scanned: int = 0
    completed: int = 0
    failed: int = 0
    fields_confirmed: int = 0
    fields_conflicted: int = 0
    fields_insufficient: int = 0
    fields_not_applicable: int = 0
    review_cases_queued: int = 0
    no_review_required: int = 0
    results: list[VerificationWorkerItemResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def master_publisher_ready(self) -> int:
        return self.no_review_required


class VerificationWorkerService:
    def __init__(self, session: Session, logger: logging.Logger | None = None) -> None:
        self.session = session
        self.logger = logger or logging.getLogger(__name__)
        self.interpreter = CandidateFieldEvidenceVerifier()

    def run(
        self,
        *,
        authority: str | None,
        candidate_key: str | None,
        batch_size: int,
        dry_run: bool,
    ) -> VerificationWorkerSummary:
        summary = VerificationWorkerSummary(authority=authority, dry_run=dry_run)
        revision_ids = self.select_eligible_revisions(
            authority=authority,
            candidate_key=candidate_key,
            batch_size=batch_size,
        )
        summary.revisions_scanned = len(revision_ids)
        self.session.rollback()
        for revision_id in revision_ids:
            try:
                result = self._process_revision(revision_id)
                if dry_run:
                    self.session.rollback()
                else:
                    self.session.commit()
                self._add_result(summary, result)
            except Exception as error:
                self.session.rollback()
                summary.failed += 1
                message = f"{revision_id}: {type(error).__name__}: {error}"
                summary.errors.append(message)
                self.logger.exception(
                    "verification_revision_failed candidate_revision_id=%s", revision_id
                )
        return summary

    def select_eligible_revisions(
        self,
        *,
        authority: str | None,
        candidate_key: str | None,
        batch_size: int,
    ) -> list[uuid.UUID]:
        statement = (
            select(RecruitmentCandidateRevision)
            .join(RecruitmentCandidateRevision.recruitment_candidate)
            .join(RecruitmentCandidate.recruiting_authority)
            .options(
                joinedload(RecruitmentCandidateRevision.recruitment_candidate),
                selectinload(RecruitmentCandidateRevision.fields),
            )
            .where(
                RecruitmentCandidate.status != CandidateStatus.DISCARDED,
                RecruitmentCandidateRevision.fields.any(),
            )
            .order_by(
                RecruitmentCandidateRevision.created_at,
                RecruitmentCandidateRevision.id,
            )
        )
        if authority:
            statement = statement.where(RecruitingAuthority.code == authority.strip().upper())
        if candidate_key:
            statement = statement.where(
                RecruitmentCandidate.candidate_key == candidate_key.strip().upper()
            )
        revisions = self.session.scalars(statement).all()
        selected = [item.id for item in revisions if self._needs_verification(item.id)]
        return selected[:batch_size]

    def _needs_verification(self, revision_id: uuid.UUID) -> bool:
        latest_current = self.session.scalar(
            select(func.max(VerificationRun.created_at))
            .join(
                RevisionConfidenceAssessment,
                RevisionConfidenceAssessment.verification_run_id == VerificationRun.id,
            )
            .where(
                VerificationRun.candidate_revision_id == revision_id,
                VerificationRun.status == VerificationRunStatus.COMPLETED,
                RevisionConfidenceAssessment.policy_version == ConfidencePolicyVersion.V1,
            )
        )
        if latest_current is None:
            return True
        latest_request = self.session.scalar(
            select(func.max(ReviewCase.resolved_at))
            .join(
                RevisionConfidenceAssessment,
                RevisionConfidenceAssessment.id
                == ReviewCase.revision_confidence_assessment_id,
            )
            .where(
                RevisionConfidenceAssessment.candidate_revision_id == revision_id,
                ReviewCase.status == ReviewCaseStatus.RESOLVED,
                ReviewCase.outcome == ReviewCaseOutcome.REVERIFICATION_REQUESTED,
            )
        )
        if latest_request is None:
            return False
        latest_run = self.session.scalar(
            select(func.max(VerificationRun.created_at)).where(
                VerificationRun.candidate_revision_id == revision_id
            )
        )
        return latest_run is None or self._timestamp(latest_request) > self._timestamp(latest_run)

    def _process_revision(self, revision_id: uuid.UUID) -> VerificationWorkerItemResult:
        revision = self.session.scalar(
            select(RecruitmentCandidateRevision)
            .options(
                joinedload(RecruitmentCandidateRevision.recruitment_candidate),
                selectinload(RecruitmentCandidateRevision.fields),
            )
            .where(RecruitmentCandidateRevision.id == revision_id)
        )
        if revision is None:
            raise RuntimeError("Candidate revision disappeared after selection")
        candidate = revision.recruitment_candidate
        if candidate.status == CandidateStatus.DRAFT:
            CandidateService(self.session, commit=False).update_candidate_status(
                candidate.id, CandidateStatus.READY_FOR_VERIFICATION
            )

        trigger = (
            VerificationTriggerType.RETRY
            if self.session.scalar(
                select(func.count(VerificationRun.id)).where(
                    VerificationRun.candidate_revision_id == revision.id
                )
            )
            else VerificationTriggerType.AUTOMATED
        )
        verification = VerificationService(self.session, commit=False)
        run = verification.create_run(
            VerificationRunCreate(candidate_revision_id=revision.id, trigger_type=trigger)
        )
        # Application precision makes one-shot reverification ordering deterministic even on
        # databases whose CURRENT_TIMESTAMP default is only second-granular.
        run.created_at = datetime.now(UTC)
        self.session.flush()
        verification.start_run(run.id)
        evidence_repository = CandidateFieldEvidenceRepository(self.session)
        for candidate_field in sorted(revision.fields, key=self._field_sort_key):
            field_verification, _ = verification.create_field_verification(
                run.id, candidate_field.id
            )
            for evidence in evidence_repository.list_evidence_for_field(candidate_field.id):
                interpretation = self.interpreter.evaluate(candidate_field, evidence)
                verification.add_assessment(
                    field_verification.id,
                    VerificationEvidenceAssessmentCreate(
                        evidence_id=evidence.id,
                        assessment=interpretation.assessment,
                        asserted_value=interpretation.asserted_value,
                        asserted_value_type=interpretation.asserted_value_type,
                        assessment_note=interpretation.note,
                    ),
                )
            verification.finalize_field_verification(
                field_verification.id, not_applicable=False
            )
        run = verification.complete_run(
            run.id, VerificationRunComplete(status=VerificationRunStatus.COMPLETED)
        )
        confidence, _, _ = ConfidenceService(self.session, commit=False).score_run(run.id)
        review_case_id = None
        if confidence.review_required:
            review_case, _ = ReviewService(self.session, commit=False).create_case(confidence.id)
            review_case_id = review_case.id
        self.logger.info(
            "verification_revision_completed candidate_revision_id=%s run_id=%s "
            "score=%s review_required=%s",
            revision.id,
            run.id,
            confidence.score,
            confidence.review_required,
        )
        return VerificationWorkerItemResult(
            candidate_revision_id=revision.id,
            verification_run_id=run.id,
            confidence_assessment_id=confidence.id,
            review_case_id=review_case_id,
            score=confidence.score,
            fields_confirmed=run.fields_confirmed,
            fields_conflicted=run.fields_conflicted,
            fields_insufficient=run.fields_insufficient,
            fields_not_applicable=run.fields_not_applicable,
            review_required=confidence.review_required,
        )

    @staticmethod
    def _field_sort_key(value: CandidateField) -> tuple[str, str]:
        return value.field_path, str(value.id)

    @staticmethod
    def _timestamp(value: datetime) -> float:
        return value.timestamp()

    @staticmethod
    def _add_result(
        summary: VerificationWorkerSummary, result: VerificationWorkerItemResult
    ) -> None:
        summary.completed += 1
        summary.fields_confirmed += result.fields_confirmed
        summary.fields_conflicted += result.fields_conflicted
        summary.fields_insufficient += result.fields_insufficient
        summary.fields_not_applicable += result.fields_not_applicable
        summary.review_cases_queued += int(result.review_required)
        summary.no_review_required += int(not result.review_required)
        summary.results.append(result)


def format_verification_summary(summary: VerificationWorkerSummary) -> str:
    mode = "DRY RUN - NO DATABASE CHANGES" if summary.dry_run else "PERSISTED"
    scores = ", ".join(str(item.score) for item in summary.results) or "n/a"
    errors = "\n".join(f"  - {item}" for item in summary.errors) or "  None"
    return f"""================================================
 Assam Job Intelligence - Verification ({mode})
 Authority: {summary.authority or 'ALL'}
================================================
Candidate revisions scanned: {summary.revisions_scanned}

VERIFICATION
  Completed:                 {summary.completed}
  Failed:                    {summary.failed}

FIELDS
  Confirmed:                 {summary.fields_confirmed}
  Conflicted:                {summary.fields_conflicted}
  Insufficient evidence:     {summary.fields_insufficient}
  Not applicable:            {summary.fields_not_applicable}

CONFIDENCE
  Revision score(s):         {scores}

ROUTING
  No review required:        {summary.no_review_required}
  Review cases queued:       {summary.review_cases_queued}

MASTER PUBLISHER READY:      {summary.master_publisher_ready}

Errors:
{errors}
Status: {'SUCCESS' if summary.failed == 0 else 'PARTIAL_FAILURE'}
================================================"""
