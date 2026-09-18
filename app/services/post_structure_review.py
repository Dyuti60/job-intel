"""Human-confirmed structure is a new interpretation, never an evidence mutation."""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidates import AdvertisementSplitStatus, CandidateValueType
from app.models.evidence import CandidateFieldEvidence
from app.models.review import ReviewCase, ReviewCaseStatus, ReviewDecisionType
from app.repositories.evidence import CandidateFieldEvidenceRepository
from app.schemas.candidates import (
    CandidateFieldCreate,
    RecruitmentCandidateRevisionCreate,
    RecruitmentPostCreate,
)
from app.schemas.review import ReviewDecisionCreate
from app.services.candidate_values import compute_persisted_revision_hash
from app.services.candidates import CandidateService
from app.services.exceptions import DomainConflictError
from app.services.post_identity import canonical_post_name, stable_post_key
from app.services.review import ReviewService
from app.services.verification_worker import VerificationWorkerService


class PostStructureReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def approve(self, case_id: uuid.UUID, rows: list[dict], reviewer: str, comment: str):
        """Caller commits/rolls back the complete operation. Shared facts remain reviewable."""
        review = ReviewService(self.session, commit=False)
        original_case = review.get_case(case_id)
        original = CandidateService(self.session, commit=False).get_revision(
            original_case.candidate_revision_id
        )
        interpretation = original.advertisement_revision
        if compute_persisted_revision_hash(original) != original.revision_hash:
            raise DomainConflictError("Original parser revision fails integrity validation")
        if (
            interpretation is not None
            and interpretation.split_status == AdvertisementSplitStatus.EXPLICIT
        ):
            raise DomainConflictError("This Advertisement already has explicit Posts")
        comment = comment.strip()
        if not comment or len(comment) > 2000:
            raise DomainConflictError("A reviewer comment of 1–2000 characters is required")
        if not 1 <= len(rows) <= 50:
            raise DomainConflictError("Propose between 1 and 50 Posts")
        posts = []
        keys = set()
        for ordinal, row in enumerate(rows, 1):
            title = " ".join(row.get("title", "").split())
            organisation = " ".join(row.get("organisation", "").split())
            if not title or len(title) > 250 or len(organisation) > 200:
                raise DomainConflictError(
                    "Each Post needs a title; title/unit must fit their limits"
                )
            if title.casefold().startswith("advertisement"):
                raise DomainConflictError("Use a Post title, not Advertisement prose")
            key = stable_post_key(title, organisation)
            if key in keys:
                raise DomainConflictError("Duplicate Post title and organisation")
            keys.add(key)
            facts = [
                CandidateFieldCreate(
                    field_path="name",
                    value_type=CandidateValueType.STRING,
                    value=canonical_post_name(title, organisation),
                )
            ]
            if organisation:
                facts.append(
                    CandidateFieldCreate(
                        field_path="organisation.name",
                        value_type=CandidateValueType.STRING,
                        value=organisation,
                    )
                )
            vacancy = str(row.get("vacancies", "")).strip()
            if vacancy:
                if not vacancy.isascii() or not vacancy.isdecimal() or len(vacancy) > 9:
                    raise DomainConflictError(
                        "Vacancies must be a non-negative whole number or unknown"
                    )
                facts.append(
                    CandidateFieldCreate(
                        field_path="vacancies.total",
                        value_type=CandidateValueType.INTEGER,
                        value=int(vacancy),
                    )
                )
            posts.append(
                RecruitmentPostCreate(
                    post_key=key,
                    ordinal=ordinal,
                    name=title,
                    normalized_name=title.casefold(),
                    facts=facts,
                )
            )
        shared = [
            field
            for field in original.fields
            if not field.field_path.startswith("posts.")
            and not field.field_path.startswith("extraction.")
        ]
        aggregate = next(
            (field.value for field in shared if field.field_path == "vacancies.total"), None
        )
        counts = [
            next((f.value for f in p.facts if f.field_path == "vacancies.total"), None)
            for p in posts
        ]
        if (
            isinstance(aggregate, int)
            and all(value is not None for value in counts)
            and sum(counts) != aggregate
        ):
            raise DomainConflictError("Post totals do not reconcile with Advertisement vacancies")
        audit = json.dumps(
            {
                "operation": "HUMAN_POST_STRUCTURE",
                "original_revision": str(original.id),
                "original_case": str(case_id),
                "parser_status": interpretation.split_status.value
                if interpretation
                else "LEGACY_UNSPLIT",
                "reviewer": reviewer,
                "comment": comment,
                "approved_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
        revision, created = CandidateService(self.session, commit=False).create_revision(
            original.recruitment_candidate_id,
            RecruitmentCandidateRevisionCreate(
                source_document_id=original.source_document_id,
                extraction_method="HUMAN_POST_STRUCTURE",
                extraction_note=audit,
                split_status=AdvertisementSplitStatus.EXPLICIT,
                split_note="Human-confirmed structure; original parser interpretation preserved.",
                fields=[
                    CandidateFieldCreate(
                        field_path=f.field_path,
                        value_type=f.value_type,
                        value=f.value,
                        raw_value=f.raw_value,
                        source_locator=f.source_locator,
                    )
                    for f in shared
                ],
                posts=posts,
            ),
        )
        if not created:
            existing = self.session.scalar(
                select(ReviewCase).where(ReviewCase.candidate_revision_id == revision.id)
            )
            if existing is None:
                raise DomainConflictError("Existing structure has no review context")
            return existing
        if original_case.status == ReviewCaseStatus.CANCELLED:
            raise DomainConflictError("A cancelled review cannot approve a new structure")
        links = CandidateFieldEvidenceRepository(self.session)
        originals = {field.field_path: field for field in shared}
        for field in revision.fields:
            if field.field_path in originals:
                for evidence in links.list_evidence_for_field(originals[field.field_path].id):
                    links.add(
                        CandidateFieldEvidence(
                            candidate_field_id=field.id,
                            evidence_id=evidence.id,
                            source_document_id=revision.source_document_id,
                        )
                    )
        self.session.flush()
        result = VerificationWorkerService(self.session).process_revision(revision.id)
        if result.review_case_id is None:
            raise DomainConflictError("Human-created Posts require a review context")
        new_case = review.start_case(result.review_case_id)
        for item in new_case.items:
            if ReviewService._post_key(item.field_path_snapshot) is not None:
                review.decide_item(
                    item.id,
                    ReviewDecisionCreate(
                        decision=ReviewDecisionType.APPROVE_AS_IS,
                        reviewer_identifier=reviewer,
                        decision_note=comment,
                    ),
                )
        if original_case.status in {ReviewCaseStatus.QUEUED, ReviewCaseStatus.IN_REVIEW}:
            review.cancel_case(original_case.id)
        return review.get_case(new_case.id)
