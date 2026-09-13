import enum
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

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
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from app.services.verification_worker import (
    VerificationWorkerService,
    VerificationWorkerSummary,
)
from sources.adapters.official_recruitment_archive import OFFICIAL_ARCHIVE_SOURCES


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
    **{
        code: PipelineSourceConfig(source=code, authority_code=config.authority_code)
        for code, config in OFFICIAL_ARCHIVE_SOURCES.items()
    },
}


@dataclass(frozen=True)
class PipelineStageExecution:
    stage: str
    status: str
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    summary: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


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
    stage_executions: list[PipelineStageExecution] = field(default_factory=list)


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
        discovery_adapter: Any = None,
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
        stage_started_at, stage_started_clock = self._start_stage()
        try:
            if key == "APSC":
                result.discovery = APSCDiscoveryWorkerService(
                    self.session, self.settings, self.logger
                ).run(dry_run=dry_run, adapter=discovery_adapter)
            else:
                result.discovery = OfficialArchiveDiscoveryWorkerService(
                    self.session,
                    self.settings,
                    self.logger,
                    OFFICIAL_ARCHIVE_SOURCES[key],
                ).run(dry_run=dry_run, adapter=discovery_adapter)
        except Exception as error:
            self.session.rollback()
            result.status = PipelineStatus.FAILED
            message = f"Discovery failed: {type(error).__name__}: {error}"
            result.errors.append(message)
            result.stage_executions.append(
                self._finish_stage(
                    "DISCOVERY",
                    "FAILED",
                    stage_started_at,
                    stage_started_clock,
                    error_code=type(error).__name__,
                    error_message=str(error),
                )
            )
            self.logger.exception("pipeline_discovery_failed source=%s", key)
            return result
        discovery_status = (
            "PARTIAL" if result.discovery.status == DiscoveryRunStatus.PARTIAL else "SUCCESS"
        )
        result.stage_executions.append(
            self._finish_stage(
                "DISCOVERY",
                discovery_status,
                stage_started_at,
                stage_started_clock,
                summary={
                    "documents_new": result.discovery.documents_new,
                    "documents_changed": result.discovery.documents_changed,
                    "documents_unchanged": result.discovery.documents_unchanged,
                    "candidates_created": result.discovery.candidates_created,
                    "candidates_reused": result.discovery.candidates_reused,
                    "revisions_created": result.discovery.revisions_created,
                    "revisions_reused": result.discovery.revisions_reused,
                },
            )
        )

        stage_started_at, stage_started_clock = self._start_stage()
        try:
            result.verification = VerificationWorkerService(self.session, self.logger).run(
                authority=config.authority_code,
                candidate_key=None,
                batch_size=self.settings.verification_batch_size,
                dry_run=dry_run,
            )
        except Exception as error:
            self.session.rollback()
            result.status = PipelineStatus.FAILED
            result.errors.append(f"Verification failed: {type(error).__name__}: {error}")
            result.stage_executions.append(
                self._finish_stage(
                    "VERIFICATION",
                    "FAILED",
                    stage_started_at,
                    stage_started_clock,
                    error_code=type(error).__name__,
                    error_message=str(error),
                )
            )
            self.logger.exception("pipeline_verification_failed source=%s", key)
            return result
        result.stage_executions.append(
            self._finish_stage(
                "VERIFICATION",
                "PARTIAL" if result.verification.failed else "SUCCESS",
                stage_started_at,
                stage_started_clock,
                summary={
                    "revisions_scanned": result.verification.revisions_scanned,
                    "completed": result.verification.completed,
                    "failed": result.verification.failed,
                    "fields_confirmed": result.verification.fields_confirmed,
                    "fields_conflicted": result.verification.fields_conflicted,
                    "fields_insufficient": result.verification.fields_insufficient,
                    "review_cases_queued": result.verification.review_cases_queued,
                },
            )
        )

        stage_started_at, stage_started_clock = self._start_stage()
        try:
            result.publisher = MasterPublisherWorkerService(self.session, self.logger).run(
                batch_size=self.settings.master_publisher_batch_size,
                dry_run=dry_run,
            )
            result.active_review_cases = self._active_review_count(config.authority_code)
        except Exception as error:
            self.session.rollback()
            result.status = PipelineStatus.FAILED
            result.errors.append(f"Master Publisher failed: {type(error).__name__}: {error}")
            result.stage_executions.append(
                self._finish_stage(
                    "MASTER_PUBLISHER",
                    "FAILED",
                    stage_started_at,
                    stage_started_clock,
                    error_code=type(error).__name__,
                    error_message=str(error),
                )
            )
            self.logger.exception("pipeline_publisher_failed source=%s", key)
            return result
        result.stage_executions.append(
            self._finish_stage(
                "MASTER_PUBLISHER",
                "PARTIAL" if result.publisher.failed else "SUCCESS",
                stage_started_at,
                stage_started_clock,
                summary={
                    "scanned": result.publisher.scanned,
                    "master_created": result.publisher.master_created,
                    "master_updated": result.publisher.master_updated,
                    "master_unchanged": result.publisher.master_unchanged,
                    "review_pending": result.publisher.review_pending,
                    "failed": result.publisher.failed,
                },
            )
        )

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

    @staticmethod
    def _start_stage() -> tuple[datetime, float]:
        return datetime.now(UTC), perf_counter()

    @staticmethod
    def _finish_stage(
        stage: str,
        status: str,
        started_at: datetime,
        started_clock: float,
        *,
        summary: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> PipelineStageExecution:
        return PipelineStageExecution(
            stage=stage,
            status=status,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            duration_ms=max(0, round((perf_counter() - started_clock) * 1000)),
            summary=summary or {},
            error_code=error_code,
            error_message=error_message,
        )

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
                    ReviewCase.status.in_((ReviewCaseStatus.QUEUED, ReviewCaseStatus.IN_REVIEW)),
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
