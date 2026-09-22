"""Audited addition of absent public-required facts before first publication."""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidates import AdvertisementSplitStatus, CandidateValueType
from app.models.evidence import CandidateFieldEvidence
from app.models.review import ReviewCase, ReviewCaseStatus
from app.repositories.evidence import CandidateFieldEvidenceRepository
from app.schemas.candidates import (
    CandidateFieldCreate,
    RecruitmentCandidateRevisionCreate,
    RecruitmentPostCreate,
)
from app.services.candidate_values import compute_persisted_revision_hash, normalize_typed_value
from app.services.candidates import CandidateService
from app.services.exceptions import DomainConflictError
from app.services.public_readiness import candidate_post_readiness
from app.services.published_maintenance import EDITABLE_FIELDS
from app.services.review import ReviewService
from app.services.verification_worker import VerificationWorkerService


class ReviewEnrichmentService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def catalogue(self, case_id: uuid.UUID, post_key: str | None) -> list[dict]:
        case = ReviewService(self.session, commit=False).get_case(case_id)
        revision = CandidateService(self.session, commit=False).get_revision(
            case.candidate_revision_id
        )
        post = (
            next(
                (
                    item
                    for item in revision.advertisement_revision.posts
                    if item.post_key == post_key
                ),
                None,
            )
            if revision.advertisement_revision
            else None
        )
        if post_key is not None and post is None:
            raise DomainConflictError("Post does not belong to this ReviewCase")
        if not candidate_post_readiness(revision, post).missing:
            return []
        existing = {field.field_path for field in revision.fields}
        allowed = {
            "vacancies.total",
            "application.start_date",
            "application.end_date",
            "qualification.minimum",
            "qualification.essential",
            "age.minimum",
            "age.maximum",
        }
        catalogue = []
        for scope, path, label, kind in EDITABLE_FIELDS:
            if path not in allowed:
                continue
            if scope == "shared" and path.startswith("application."):
                key = path
            elif scope == "post" and post is not None and not path.startswith("application."):
                key = f"posts.{post.post_key}.{path}"
            elif scope == "post" and post is None and not path.startswith("application."):
                key = path
            else:
                continue
            if key not in existing:
                catalogue.append({"key": key, "label": label, "value_type": kind.value})
        return catalogue

    def submit(
        self,
        case_id: uuid.UUID,
        post_key: str | None,
        changes: dict[str, str],
        reviewer: str,
        comment: str,
    ) -> ReviewCase:
        comment = comment.strip()
        if not comment or len(comment) > 8000:
            raise DomainConflictError("A reviewer comment of 1–8000 characters is required")
        review = ReviewService(self.session, commit=False)
        case = review.get_case(case_id)
        if case.status not in {ReviewCaseStatus.QUEUED, ReviewCaseStatus.IN_REVIEW}:
            raise DomainConflictError("Only active unpublished reviews can be enriched")
        source = CandidateService(self.session, commit=False).get_revision(
            case.candidate_revision_id
        )
        if compute_persisted_revision_hash(source) != source.revision_hash:
            raise DomainConflictError("Candidate revision fails integrity validation")
        catalogue = {item["key"]: item for item in self.catalogue(case_id, post_key)}
        if not changes or set(changes) - set(catalogue):
            raise DomainConflictError("Only missing supported attributes can be added")
        parsed = {}
        for key, raw in changes.items():
            if not raw.strip():
                continue
            kind = CandidateValueType(catalogue[key]["value_type"])
            try:
                value = normalize_typed_value(
                    kind, int(raw) if kind == CandidateValueType.INTEGER else raw.strip()
                )
            except (ValueError, TypeError) as error:
                raise DomainConflictError(f"Invalid value for {key}: {error}") from error
            if kind == CandidateValueType.INTEGER and value < 0:
                raise DomainConflictError(f"{key} cannot be negative")
            parsed[key] = CandidateFieldCreate(field_path=key, value_type=kind, value=value)
        if not parsed:
            raise DomainConflictError("Enter at least one missing attribute")
        shared = [
            CandidateFieldCreate(
                field_path=f.field_path,
                value_type=f.value_type,
                value=f.value,
                raw_value=f.raw_value,
                source_locator=f.source_locator,
            )
            for f in source.fields
            if not f.field_path.startswith("posts.")
        ]
        shared.extend(value for key, value in parsed.items() if not key.startswith("posts."))
        posts = []
        interpretation = source.advertisement_revision
        for post in interpretation.posts if interpretation else []:
            prefix = f"posts.{post.post_key}."
            facts = [
                CandidateFieldCreate(
                    field_path=f.fact_key,
                    value_type=f.candidate_field.value_type,
                    value=f.candidate_field.value,
                    raw_value=f.candidate_field.raw_value,
                    source_locator=f.candidate_field.source_locator,
                )
                for f in post.facts
            ]
            facts.extend(
                CandidateFieldCreate(
                    field_path=key.removeprefix(prefix),
                    value_type=value.value_type,
                    value=value.value,
                )
                for key, value in parsed.items()
                if key.startswith(prefix)
            )
            posts.append(
                RecruitmentPostCreate(
                    post_key=post.post_key,
                    ordinal=post.ordinal,
                    name=post.name,
                    normalized_name=post.normalized_name,
                    source_locator=post.source_locator,
                    facts=facts,
                )
            )
        audit = json.dumps(
            {
                "operation": "PUBLIC_READINESS_ENRICHMENT",
                "source_revision": str(source.id),
                "source_case": str(case.id),
                "post_key": post_key,
                "reviewer": reviewer,
                "comment": comment,
                "added": sorted(parsed),
                "submitted_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
        successor, created = CandidateService(self.session, commit=False).create_revision(
            source.recruitment_candidate_id,
            RecruitmentCandidateRevisionCreate(
                source_document_id=source.source_document_id,
                extraction_method="HUMAN_PUBLIC_ENRICHMENT",
                extraction_note=audit,
                split_status=interpretation.split_status
                if interpretation
                else AdvertisementSplitStatus.LEGACY_UNSPLIT,
                split_note=interpretation.split_note if interpretation else None,
                fields=shared,
                posts=posts,
            ),
        )
        if not created:
            existing = self.session.scalar(
                select(ReviewCase).where(ReviewCase.candidate_revision_id == successor.id)
            )
            if existing is None:
                raise DomainConflictError("Equivalent revision has no review context")
            return existing
        links = CandidateFieldEvidenceRepository(self.session)
        originals = {field.field_path: field for field in source.fields}
        for field in successor.fields:
            if field.field_path in parsed:
                continue
            old = originals.get(field.field_path)
            if old is None or old.value != field.value:
                continue
            for evidence in links.list_evidence_for_field(old.id):
                links.add(
                    CandidateFieldEvidence(
                        candidate_field_id=field.id,
                        evidence_id=evidence.id,
                        source_document_id=successor.source_document_id,
                    )
                )
        self.session.flush()
        result = VerificationWorkerService(self.session).process_revision(successor.id)
        if result.review_case_id is None:
            raise DomainConflictError("Enrichment requires a new Human Review context")
        review.cancel_case(case.id)
        return review.get_case(result.review_case_id)
