import argparse
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.services.operational_monitoring import OperationalNotificationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate pipeline health and route deduplicated local notifications."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    try:
        with SessionLocal() as session:
            summary = OperationalNotificationService(session, settings, logger).run(
                args.source,
                dry_run=args.dry_run,
            )
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as error:
        logger.exception("operational_monitor_failed source=%s", args.source)
        print(f"Operational monitoring failed: {error}")
        return 1
    print("=" * 48)
    print(" Assam Job Intelligence - Operational Monitor")
    print(f" Source: {summary.source_code}")
    print("=" * 48)
    print(f" Health:                    {summary.status}")
    print(f" Alerts detected:           {summary.alerts_detected}")
    print(f" Notifications created:     {summary.notifications_created}")
    print(f" Notifications deduplicated:{summary.notifications_deduplicated:>6}")
    print(f" Deliveries failed:         {summary.deliveries_failed}")
    print(f" Dry run:                   {summary.dry_run}")
    print("=" * 48)
    return 1 if summary.deliveries_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
