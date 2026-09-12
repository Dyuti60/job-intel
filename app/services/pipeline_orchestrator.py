import enum
import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.candidates import RecruitmentCandidate, RecruitmentCandidateRevision
from app.models.discovery import DiscoveryRunStatus
from app.models.review import ReviewCase, ReviewCaseStatus
from app.models.source_registry import RecruitingAuthority
from app.services.apsc_discovery import APSCDiscoveryWorkerService, DiscoverySummary
from app.services.master_publisher_worker import (
    MasterPublisherWorkerService,
    MasterPublisherWorkerSummary,
)
from app.services.verification_worker import (
    VerificationWorkerService,
    VerificationWorkerSummary,
)
from sources.adapters.apsc_recruitment import APSCRecruitmentAdapter


class PipelineStatus(enum.StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PipelineSourceConfig:
    source: str
    authority_code: str


PIPELINE_SOURCES = {
    "APSC": PipelineSourceConfig(source="APSC", authority_code="APSC"),
}


@dataclass
class PipelineSummary:
    source: str
    authority_code: str
    dry_run: bool
    status: PipelineStatus
    discovery: DiscoverySummary | None = None
    verification: VerificationWorkerSummary | None = None
    publisher: MasterPublisherWorkerSummary | None = None
    active_review_cases: int = 0
    errors: list[str] = field(default_factory=list)


class PipelineOrchestratorService:
    """Coordinate existing one-shot workers without owning their domain rules."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        logger: logging.Logger | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)

    def run(
        self,
        *,
        source: str,
        dry_run: bool = False,
        discovery_adapter: APSCRecruitmentAdapter | None = None,
    ) -> PipelineSummary:
        key = source.strip().upper()
        config = PIPELINE_SOURCES.get(key)
        if config is None:
            return PipelineSummary(
                source=key,
                authority_code=key,
                dry_run=dry_run,
                status=PipelineStatus.FAILED,
                errors=[f"Unsupported pipeline source: {key}"],
            )
        result = PipelineSummary(
            source=config.source,
            authority_code=config.authority_code,
            dry_run=dry_run,
            status=PipelineStatus.SUCCESS,
        )
        self.logger.info("pipeline_started source=%s dry_run=%s", key, dry_run)
        try:
            result.discovery = APSCDiscoveryWorkerService(
                self.session, self.settings, self.logger
            ).run(dry_run=dry_run, adapter=discovery_adapter)
        except Exception as error:
            self.session.rollback()
            result.status = PipelineStatus.FAILED
            result.errors.append(f"Discovery failed: {type(error).__name__}: {error}")
            self.logger.exception("pipeline_discovery_failed source=%s", key)
            return result

        try:
            result.verification = VerificationWorkerService(
                self.session, self.logger
            ).run(
                authority=config.authority_code,
                candidate_key=None,
                batch_size=self.settings.verification_batch_size,
                dry_run=dry_run,
            )
        except Exception as error:
            self.session.rollback()
            result.status = PipelineStatus.FAILED
            result.errors.append(f"Verification failed: {type(error).__name__}: {error}")
            self.logger.exception("pipeline_verification_failed source=%s", key)
            return result

        try:
            result.publisher = MasterPublisherWorkerService(
                self.session, self.logger
            ).run(
                batch_size=self.settings.master_publisher_batch_size,
                dry_run=dry_run,
            )
            result.active_review_cases = self._active_review_count(config.authority_code)
        except Exception as error:
            self.session.rollback()
            result.status = PipelineStatus.FAILED
            result.errors.append(f"Master Publisher failed: {type(error).__name__}: {error}")
            self.logger.exception("pipeline_publisher_failed source=%s", key)
            return result

        if (
            result.discovery.status == DiscoveryRunStatus.PARTIAL
            or result.verification.failed
            or result.publisher.failed
        ):
            result.status = PipelineStatus.PARTIAL
        self.logger.info(
            "pipeline_finished source=%s status=%s active_reviews=%s",
            key,
            result.status.value,
            result.active_review_cases,
        )
        return result

    def _active_review_count(self, authority_code: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(ReviewCase.id))
                .join(
                    RecruitmentCandidateRevision,
                    RecruitmentCandidateRevision.id == ReviewCase.candidate_revision_id,
                )
                .join(
                    RecruitmentCandidate,
                    RecruitmentCandidate.id
                    == RecruitmentCandidateRevision.recruitment_candidate_id,
                )
                .join(
                    RecruitingAuthority,
                    RecruitingAuthority.id == RecruitmentCandidate.recruiting_authority_id,
                )
                .where(
                    RecruitingAuthority.code == authority_code,
                    ReviewCase.status.in_(
                        (ReviewCaseStatus.QUEUED, ReviewCaseStatus.IN_REVIEW)
                    ),
                )
            )
            or 0
        )


def format_pipeline_summary(summary: PipelineSummary) -> str:
    discovery = summary.discovery
    verification = summary.verification
    publisher = summary.publisher
    errors = "\n".join(f"  - {item}" for item in summary.errors) or "  None"
    return "\n".join(
        [
            "================================================",
            f" Assam Job Intelligence - Pipeline{' (DRY RUN)' if summary.dry_run else ''}",
            f" Source: {summary.source}",
            "================================================",
            "",
            "DISCOVERY",
            f"  Status:                     {discovery.status if discovery else 'NOT RUN'}",
            f"  Documents new:              {discovery.documents_new if discovery else 0}",
            f"  Documents changed:          {discovery.documents_changed if discovery else 0}",
            f"  Documents unchanged:        {discovery.documents_unchanged if discovery else 0}",
            f"  Candidates created:         {discovery.candidates_created if discovery else 0}",
            f"  Candidates reused:          {discovery.candidates_reused if discovery else 0}",
            f"  Revisions created:          {discovery.revisions_created if discovery else 0}",
            f"  Revisions reused:           {discovery.revisions_reused if discovery else 0}",
            "",
            "VERIFICATION",
            f"  Revisions processed:        {verification.completed if verification else 0}",
            f"  Revisions failed:           {verification.failed if verification else 0}",
            f"  Fields confirmed:           {verification.fields_confirmed if verification else 0}",
            "  Fields conflicted:          "
            f"{verification.fields_conflicted if verification else 0}",
            "  Fields insufficient:        "
            f"{verification.fields_insufficient if verification else 0}",
            "",
            "REVIEW ROUTING",
            "  New cases queued:           "
            f"{verification.review_cases_queued if verification else 0}",
            f"  Existing active cases:      {summary.active_review_cases}",
            "",
            "MASTER PUBLISHER",
            f"  Created:                    {publisher.master_created if publisher else 0}",
            f"  Updated:                    {publisher.master_updated if publisher else 0}",
            f"  Unchanged:                  {publisher.master_unchanged if publisher else 0}",
            f"  Skipped pending review:     {publisher.review_pending if publisher else 0}",
            f"  Rejected:                   {publisher.rejected if publisher else 0}",
            "  Reverification requested:   "
            f"{publisher.reverification_requested if publisher else 0}",
            "",
            "ACTION REQUIRED",
            f"  Human Review:               {summary.active_review_cases}",
            "",
            "Review UI:",
            "  http://localhost:8000/review",
            "",
            "Errors:",
            errors,
            f"Status: {summary.status.value}",
            "================================================",
        ]
    )
