import argparse
import json
import uuid
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.candidates import RecruitmentCandidateRevision
from app.models.discovery import SourceDocument
from sources.adapters.official_recruitment_archive import (
    ArchiveNoticeMetadata,
    extraction_diagnostic_summary,
    parse_official_advertisement_text,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect one persisted recruitment PDF without changing domain state."
    )
    parser.add_argument("--source-document", required=True, type=uuid.UUID)
    return parser


def main() -> None:
    args = _parser().parse_args()
    settings = get_settings()
    with SessionLocal() as session:
        document = session.get(SourceDocument, args.source_document)
        if document is None:
            raise SystemExit("SourceDocument was not found")
        revision = session.scalar(
            select(RecruitmentCandidateRevision)
            .where(RecruitmentCandidateRevision.source_document_id == document.id)
            .order_by(RecruitmentCandidateRevision.revision_number.desc())
            .limit(1)
        )
        if revision is None:
            raise SystemExit("SourceDocument has no Candidate revision")
        if not document.storage_uri or not document.storage_uri.startswith("raw://"):
            raise SystemExit("SourceDocument has no readable local raw:// object")
        path = Path(settings.raw_storage_root) / document.storage_uri.removeprefix("raw://")
        if not path.is_file():
            raise SystemExit("Persisted raw PDF was not found")
        reader = PdfReader(path)
        page_texts = [(page.extract_text() or "") for page in reader.pages[:30]]
        candidate = revision.recruitment_candidate
        extraction = parse_official_advertisement_text(
            "\n".join(page_texts),
            ArchiveNoticeMetadata(
                title=candidate.display_name,
                document_url=document.document_url,
                notification_number=None,
                notification_date=None,
            ),
            candidate.recruiting_authority.name,
        )
        report = extraction_diagnostic_summary(
            document_url=document.document_url,
            page_texts=page_texts,
            extraction=extraction,
        )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
