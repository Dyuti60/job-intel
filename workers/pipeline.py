import argparse
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    try:
        with SessionLocal() as session:
            summary = PipelineOrchestratorService(session, settings, logger).run(
                source=args.source,
                dry_run=args.dry_run,
            )
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as error:
        logger.exception("pipeline_worker_level_failure source=%s", args.source)
        print(f"Pipeline failed before a safe summary could be produced: {error}")
        return 1
    print(format_pipeline_summary(summary))
    return 1 if summary.status == PipelineStatus.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
