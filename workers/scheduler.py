import argparse
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.pipeline import PipelineTriggerType
from app.models.source_registry import SourceScheduleGroup
from app.services.pipeline_orchestrator import PIPELINE_SOURCES
from app.services.source_scheduler import (
    SchedulerSelection,
    SourceSchedulerService,
    format_scheduler_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic registered Assam sources.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--source", choices=tuple(PIPELINE_SOURCES))
    target.add_argument("--group", choices=tuple(SourceScheduleGroup), type=SourceScheduleGroup)
    target.add_argument("--due", action="store_true")
    target.add_argument("--all-enabled", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview scheduler selection only; do not fetch sources or execute pipelines.",
    )
    mode.add_argument(
        "--execute-no-commit",
        action="store_true",
        help="Execute the complete source pipeline without committing recruitment-domain changes.",
    )
    parser.add_argument(
        "--trigger",
        choices=tuple(PipelineTriggerType),
        default=PipelineTriggerType.CLI,
        type=PipelineTriggerType,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selection = (
        SchedulerSelection.SOURCE
        if args.source
        else SchedulerSelection.GROUP
        if args.group
        else SchedulerSelection.DUE
        if args.due
        else SchedulerSelection.ALL
    )
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    try:
        with SessionLocal() as session:
            summary = SourceSchedulerService(session, settings, logger).run(
                selection,
                source=args.source,
                group=args.group,
                dry_run=args.dry_run,
                execute_no_commit=args.execute_no_commit,
                trigger_type=args.trigger,
            )
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as error:
        logger.exception("scheduler_failure")
        print(f"Scheduler failed before a safe summary could be produced: {error}")
        return 1
    print(format_scheduler_summary(summary))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
