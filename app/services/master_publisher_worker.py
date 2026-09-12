import enum
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.master import PublicationPath
from app.models.review import ReviewCaseOutcome, ReviewCaseStatus
from app.repositories.confidence import RevisionConfidenceRepository
from app.repositories.review import ReviewCaseRepository
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.master import MasterPublisherService


class PublicationCandidateKind(enum.StrEnum):
    DIRECT = "DIRECT"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_CORRECTED = "HUMAN_CORRECTED"
    REVIEW_MISSING = "REVIEW_MISSING"
    REVIEW_PENDING = "REVIEW_PENDING"
    REVIEW_CANCELLED = "REVIEW_CANCELLED"
    REJECTED = "REJECTED"
    REVERIFICATION_REQUESTED = "REVERIFICATION_REQUESTED"


@dataclass
class MasterPublisherWorkerSummary:
    dry_run: bool
    scanned: int = 0
    direct_verified: int = 0
    human_approved: int = 0
    human_corrected: int = 0
    master_created: int = 0
    master_updated: int = 0
    master_unchanged: int = 0
    review_missing: int = 0
    review_pending: int = 0
    review_cancelled: int = 0
    rejected: int = 0
    reverification_requested: int = 0
    failed: int = 0
    scanned_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.dry_run:
            return "DRY_RUN"
        return "COMPLETED_WITH_ERRORS" if self.failed else "SUCCESS"


class MasterPublisherWorkerService:
    """Orchestrate pending assessments without owning publication rules."""

    def __init__(self, session: Session, logger: logging.Logger | None = None) -> None:
        self.session = session
        self.logger = logger or logging.getLogger(__name__)
        self.confidence = RevisionConfidenceRepository(session)
        self.review_cases = ReviewCaseRepository(session)

    def run(self, *, batch_size: int, dry_run: bool = False) -> MasterPublisherWorkerSummary:
        summary = MasterPublisherWorkerSummary(dry_run=dry_run)
        assessment_ids = self.confidence.list_pending_publication_ids(limit=batch_size)
        summary.scanned = len(assessment_ids)
        summary.scanned_ids.extend(assessment_ids)
        self.logger.info(
            "master_publisher_worker_started batch_size=%s dry_run=%s scanned=%s",
            batch_size,
            dry_run,
            summary.scanned,
        )
        for assessment_id in assessment_ids:
            self._process(assessment_id, summary)
        self.logger.info(
            "master_publisher_worker_finished status=%s scanned=%s failed=%s",
            summary.status,
            summary.scanned,
            summary.failed,
        )
        return summary

    def _process(
        self,
        assessment_id: uuid.UUID,
        summary: MasterPublisherWorkerSummary,
    ) -> None:
        self.logger.info("master_publication_assessment_processing id=%s", assessment_id)
        assessment = self.confidence.get(assessment_id)
        if assessment is None:
            self._failed(summary, assessment_id, "assessment disappeared during processing")
            return
        try:
            kind = self._classify(assessment)
        except DomainConflictError as error:
            self.session.rollback()
            self._failed(summary, assessment_id, str(error))
            return
        if kind not in {
            PublicationCandidateKind.DIRECT,
            PublicationCandidateKind.HUMAN_APPROVED,
            PublicationCandidateKind.HUMAN_CORRECTED,
        }:
            self._skip(summary, assessment_id, kind)
            return

        publisher = MasterPublisherService(self.session)
        try:
            if summary.dry_run:
                preview = publisher.preview(assessment_id)
                self._assert_path(kind, preview.publication_path)
                self._count_publishable(summary, kind)
                self._count_result(
                    summary,
                    master_exists=preview.master_exists,
                    revision_exists=preview.matching_revision_exists,
                )
                self.session.rollback()
                self.logger.info(
                    "master_publication_dry_run id=%s path=%s",
                    assessment_id,
                    preview.publication_path.value,
                )
                return

            _, revision, event, revision_created = publisher.publish(assessment_id)
            self._assert_path(kind, event.publication_path)
            self._count_publishable(summary, kind)
            self._count_result(
                summary,
                master_exists=revision.revision_number > 1 or not revision_created,
                revision_exists=not revision_created,
            )
            self.logger.info(
                "master_publication_succeeded id=%s path=%s result=%s master_revision_id=%s",
                assessment_id,
                event.publication_path.value,
                event.result.value,
                revision.id,
            )
        except (DomainConflictError, ResourceNotFoundError) as error:
            self.session.rollback()
            self._failed(summary, assessment_id, str(error))
        except SQLAlchemyError:
            self.session.rollback()
            raise
        except Exception as error:  # defensive isolation for one corrupt domain item
            self.session.rollback()
            self._failed(summary, assessment_id, str(error))

    def _classify(self, assessment) -> PublicationCandidateKind:
        if not assessment.review_required:
            return PublicationCandidateKind.DIRECT
        review_case = self.review_cases.get_by_confidence_assessment(assessment.id)
        if review_case is None:
            return PublicationCandidateKind.REVIEW_MISSING
        if review_case.status in {ReviewCaseStatus.QUEUED, ReviewCaseStatus.IN_REVIEW}:
            return PublicationCandidateKind.REVIEW_PENDING
        if review_case.status == ReviewCaseStatus.CANCELLED:
            return PublicationCandidateKind.REVIEW_CANCELLED
        if review_case.status != ReviewCaseStatus.RESOLVED:
            raise DomainConflictError("ReviewCase has an unsupported publication state")
        if review_case.outcome == ReviewCaseOutcome.APPROVED:
            return PublicationCandidateKind.HUMAN_APPROVED
        if review_case.outcome == ReviewCaseOutcome.APPROVED_WITH_CORRECTIONS:
            return PublicationCandidateKind.HUMAN_CORRECTED
        if review_case.outcome == ReviewCaseOutcome.REJECTED:
            return PublicationCandidateKind.REJECTED
        if review_case.outcome == ReviewCaseOutcome.REVERIFICATION_REQUESTED:
            return PublicationCandidateKind.REVERIFICATION_REQUESTED
        raise DomainConflictError("Resolved ReviewCase has no supported outcome")

    def _skip(
        self,
        summary: MasterPublisherWorkerSummary,
        assessment_id: uuid.UUID,
        kind: PublicationCandidateKind,
    ) -> None:
        attribute = {
            PublicationCandidateKind.REVIEW_MISSING: "review_missing",
            PublicationCandidateKind.REVIEW_PENDING: "review_pending",
            PublicationCandidateKind.REVIEW_CANCELLED: "review_cancelled",
            PublicationCandidateKind.REJECTED: "rejected",
            PublicationCandidateKind.REVERIFICATION_REQUESTED: "reverification_requested",
        }[kind]
        setattr(summary, attribute, getattr(summary, attribute) + 1)
        self.logger.info(
            "master_publication_skipped id=%s reason=%s", assessment_id, kind.value
        )

    def _failed(
        self,
        summary: MasterPublisherWorkerSummary,
        assessment_id: uuid.UUID,
        reason: str,
    ) -> None:
        summary.failed += 1
        self.logger.error(
            "master_publication_failed id=%s reason=%s", assessment_id, reason
        )

    @staticmethod
    def _assert_path(kind: PublicationCandidateKind, path: PublicationPath) -> None:
        expected = {
            PublicationCandidateKind.DIRECT: PublicationPath.VERIFIED_NO_REVIEW,
            PublicationCandidateKind.HUMAN_APPROVED: PublicationPath.HUMAN_APPROVED,
            PublicationCandidateKind.HUMAN_CORRECTED: PublicationPath.HUMAN_CORRECTED,
        }[kind]
        if path != expected:
            raise DomainConflictError("Publisher returned an unexpected publication path")

    @staticmethod
    def _count_publishable(
        summary: MasterPublisherWorkerSummary,
        kind: PublicationCandidateKind,
    ) -> None:
        if kind == PublicationCandidateKind.DIRECT:
            summary.direct_verified += 1
        elif kind == PublicationCandidateKind.HUMAN_APPROVED:
            summary.human_approved += 1
        else:
            summary.human_corrected += 1

    @staticmethod
    def _count_result(
        summary: MasterPublisherWorkerSummary,
        *,
        master_exists: bool,
        revision_exists: bool,
    ) -> None:
        if revision_exists:
            summary.master_unchanged += 1
        elif master_exists:
            summary.master_updated += 1
        else:
            summary.master_created += 1


def format_master_publisher_summary(summary: MasterPublisherWorkerSummary) -> str:
    mode = " (DRY RUN)" if summary.dry_run else ""
    return "\n".join(
        [
            "================================================",
            f" Assam Job Intelligence - Master Publisher{mode}",
            "================================================",
            "",
            f"Scanned:                     {summary.scanned:>5}",
            "",
            "PUBLISHABLE",
            f"  Direct verified:           {summary.direct_verified:>5}",
            f"  Human approved:            {summary.human_approved:>5}",
            f"  Human corrected:           {summary.human_corrected:>5}",
            "",
            "RESULTS" if not summary.dry_run else "WOULD RESULT",
            f"  Master created:            {summary.master_created:>5}",
            f"  Master updated:            {summary.master_updated:>5}",
            f"  Master unchanged:          {summary.master_unchanged:>5}",
            "",
            "SKIPPED",
            f"  Review required/missing:   {summary.review_missing:>5}",
            f"  Review pending:            {summary.review_pending:>5}",
            f"  Review cancelled:          {summary.review_cancelled:>5}",
            f"  Rejected:                  {summary.rejected:>5}",
            f"  Reverification requested:  {summary.reverification_requested:>5}",
            "",
            "FAILED",
            f"  Integrity/domain errors:   {summary.failed:>5}",
            "",
            f"Status: {summary.status}",
            "================================================",
        ]
    )
