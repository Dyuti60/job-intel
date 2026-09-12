import argparse
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.services.verification_worker import (
    VerificationWorkerService,
    format_verification_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify persisted candidate revisions without network access."
    )
    parser.add_argument("--authority", required=True)
    parser.add_argument("--candidate-key")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    logger.info(
        "verification_worker_started authority=%s candidate_key=%s dry_run=%s",
        args.authority,
        args.candidate_key,
        args.dry_run,
    )
    try:
        with SessionLocal() as session:
            summary = VerificationWorkerService(session, logger).run(
                authority=args.authority,
                candidate_key=args.candidate_key,
                batch_size=settings.verification_batch_size,
                dry_run=args.dry_run,
            )
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as error:
        logger.exception("verification_worker_level_failure")
        print(f"Verification failed safely: {error}")
        return 1
    print(format_verification_summary(summary))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
