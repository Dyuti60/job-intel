import argparse
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.services.master_publisher_worker import (
    MasterPublisherWorkerService,
    format_master_publisher_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish eligible confidence assessments into Recruitment Master."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and validate pending work without changing Master persistence.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    logger.info("master_publisher_command_started dry_run=%s", args.dry_run)
    try:
        with SessionLocal() as session:
            summary = MasterPublisherWorkerService(session, logger).run(
                batch_size=settings.master_publisher_batch_size,
                dry_run=args.dry_run,
            )
    except (SQLAlchemyError, OSError) as error:
        logger.exception("master_publisher_worker_level_failure error=%s", error)
        print("Master Publisher failed before the batch could complete. See logs for details.")
        return 1
    print(format_master_publisher_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
