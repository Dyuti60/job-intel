import argparse
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.services.apsc_discovery import APSCDiscoveryWorkerService, format_discovery_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one bounded official-source discovery.")
    parser.add_argument("--source", required=True, choices=("APSC",))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    try:
        with SessionLocal() as session:
            summary = APSCDiscoveryWorkerService(session, settings, logger).run(
                dry_run=args.dry_run
            )
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as error:
        logger.exception("discovery_worker_level_failure source=%s", args.source)
        print(f"Discovery failed safely: {error}")
        return 1
    print(format_discovery_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
