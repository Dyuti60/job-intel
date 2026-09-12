import argparse
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.pipeline import PipelineTriggerType
from app.services.pipeline_history import PipelineHistoryService
from app.services.pipeline_lock import PipelineAdvisoryLock
from app.services.pipeline_orchestrator import (
    PIPELINE_SOURCES,
    PipelineOrchestratorService,
    PipelineStatus,
    format_pipeline_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one source through Discovery, Verification, and Master publishing."
    )
    parser.add_argument("--source", required=True, choices=tuple(PIPELINE_SOURCES))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--trigger",
        choices=tuple(PipelineTriggerType),
        default=PipelineTriggerType.CLI,
        type=PipelineTriggerType,
        help="Operational trigger recorded on PipelineRun (default: CLI).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    try:
        with SessionLocal() as session:
            engine = session.get_bind()
            with PipelineAdvisoryLock(engine, args.source).acquire() as acquired:
                if not acquired:
                    logger.warning("pipeline_overlap_rejected source=%s", args.source)
                    print(
                        f"Pipeline overlap rejected for {args.source}: "
                        "another execution currently holds the database advisory lock."
                    )
                    return 2
                summary, pipeline_run = PipelineHistoryService(session).execute(
                    PipelineOrchestratorService(session, settings, logger),
                    source=args.source,
                    dry_run=args.dry_run,
                    trigger_type=args.trigger,
                )
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as error:
        logger.exception("pipeline_worker_level_failure source=%s", args.source)
        print(f"Pipeline failed before a safe summary could be produced: {error}")
        return 1
    print(format_pipeline_summary(summary))
    print(f"Operational PipelineRun: {pipeline_run.id}")
    return 1 if summary.status == PipelineStatus.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
