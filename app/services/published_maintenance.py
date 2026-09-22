"""Operator maintenance of current published facts through immutable domain revisions."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.candidates import CandidateField, CandidateValueType, RecruitmentCandidateRevision
from app.models.confidence import RevisionConfidenceAssessment
from app.models.evidence import CandidateFieldEvidence
from app.models.master import (
    MasterField,
    MasterPost,
    PublicationPath,
    RecruitmentMaster,
    RecruitmentMasterRevision,
    RecruitmentMasterStatus,
)
from app.models.review import ReviewDecisionType
from app.models.source_registry import RecruitingAuthority
from app.repositories.evidence import CandidateFieldEvidenceRepository
from app.schemas.candidates import (
    CandidateFieldCreate,
    RecruitmentCandidateRevisionCreate,
    RecruitmentPostCreate,
)
from app.schemas.review import ReviewDecisionCreate
from app.services.candidate_values import compute_persisted_revision_hash, normalize_typed_value
from app.services.candidates import CandidateService
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.master import MasterPublisherService
from app.services.post_identity import canonical_post_name
from app.services.public_readiness import master_post_readiness
from app.services.review import ReviewService
from app.services.verification_worker import VerificationWorkerService

# These are existing Candidate/Master field paths, not an alternate field model.
EDITABLE_FIELDS: tuple[tuple[str, str, str, CandidateValueType], ...] = (
    ("post", "name", "Post title", CandidateValueType.STRING),
    ("post", "organisation.name", "Organisation / unit", CandidateValueType.STRING),
    ("post", "vacancies.total", "Post vacancies", CandidateValueType.INTEGER),
    ("post", "qualification.minimum", "Minimum qualification", CandidateValueType.STRING),
    ("post", "qualification.essential", "Essential qualification", CandidateValueType.STRING),
    ("post", "age.minimum", "Minimum age", CandidateValueType.INTEGER),
    ("post", "age.maximum", "Maximum age", CandidateValueType.INTEGER),
    ("post", "experience.minimum", "Minimum experience", CandidateValueType.STRING),
    ("post", "pay.scale", "Pay scale / salary", CandidateValueType.STRING),
    ("post", "domicile.requirement", "Domicile requirement", CandidateValueType.STRING),
    ("post", "selection.process", "Post selection process", CandidateValueType.STRING),
    ("post", "physical.criteria", "Physical criteria (JSON)", CandidateValueType.JSON),
    ("post", "medical.criteria", "Medical criteria (JSON)", CandidateValueType.JSON),
    ("shared", "application.start_date", "Opening date", CandidateValueType.DATE),
    ("shared", "application.end_date", "Closing date", CandidateValueType.DATE),
    ("shared", "application.mode", "Application mode", CandidateValueType.STRING),
    (
        "shared",
        "advertisement.vacancies.total",
        "Advertisement vacancies",
        CandidateValueType.INTEGER,
    ),
    ("shared", "application.url", "Application URL", CandidateValueType.STRING),
    ("shared", "application.where_to_apply", "Where to apply", CandidateValueType.STRING),
)


def _render(value: Any) -> str:
    if value is None:
        return ""
    return (
        json.dumps(value, ensure_ascii=False, indent=2)
        if isinstance(value, (list, dict))
        else str(value)
    )


class PublishedMaintenanceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _current(
        self, public_id: uuid.UUID, *, lock: bool = False
    ) -> tuple[RecruitmentMaster, MasterPost | None]:
        master_id = self.session.scalar(
            select(RecruitmentMaster.id)
            .join(
                RecruitmentMasterRevision,
                RecruitmentMaster.current_revision_id == RecruitmentMasterRevision.id,
            )
            .outerjoin(MasterPost, MasterPost.master_revision_id == RecruitmentMasterRevision.id)
            .where(
                RecruitmentMaster.status == RecruitmentMasterStatus.ACTIVE,
                or_(
                    MasterPost.public_id == public_id,
                    and_(RecruitmentMaster.id == public_id, MasterPost.id.is_(None)),
                ),
            )
            .limit(1)
        )
        if master_id is None:
            raise ResourceNotFoundError("Published job not found")
        statement = (
            select(RecruitmentMaster)
            .execution_options(populate_existing=True)
            .options(
                selectinload(RecruitmentMaster.current_revision).selectinload(
                    RecruitmentMasterRevision.fields
                ),
                selectinload(RecruitmentMaster.current_revision)
                .selectinload(RecruitmentMasterRevision.posts)
                .selectinload(MasterPost.facts),
            )
            .where(RecruitmentMaster.id == master_id)
        )
        if lock:
            statement = statement.with_for_update()
        master = self.session.scalar(statement)
        if master is not None and master.current_revision is not None:
            if master.current_revision.posts:
                for post in master.current_revision.posts:
                    if post.public_id == public_id:
                        return master, post
            elif master.id == public_id:
                return master, None
        raise ResourceNotFoundError("Published job not found")

    @staticmethod
    def _fields(master: RecruitmentMaster, post: MasterPost | None) -> dict[str, MasterField]:
        revision = master.current_revision
        assert revision is not None
        shared = {
            field.field_path: field
            for field in revision.fields
            if not field.field_path.startswith("posts.")
        }
        if post is None:
            return shared
        by_id = {field.id: field for field in revision.fields}
        return {**shared, **{fact.fact_key: by_id[fact.master_field_id] for fact in post.facts}}

    def rows(self, view: str | None = None) -> list[dict[str, Any]]:
        masters = self.session.scalars(
            select(RecruitmentMaster)
            .options(
                selectinload(RecruitmentMaster.current_revision).selectinload(
                    RecruitmentMasterRevision.fields
                ),
                selectinload(RecruitmentMaster.current_revision)
                .selectinload(RecruitmentMasterRevision.posts)
                .selectinload(MasterPost.facts),
            )
            .where(RecruitmentMaster.status == RecruitmentMasterStatus.ACTIVE)
            .order_by(RecruitmentMaster.last_published_at.desc(), RecruitmentMaster.id)
        ).all()
        authority_ids = {master.recruiting_authority_id for master in masters}
        authorities = (
            {
                item.id: item
                for item in self.session.scalars(
                    select(RecruitingAuthority).where(RecruitingAuthority.id.in_(authority_ids))
                )
            }
            if authority_ids
            else {}
        )
        rows = []
        for master in masters:
            revision = master.current_revision
            if revision is None:
                continue
            path = revision.publication_path
            category = (
                "AUTO_PUBLISHED"
                if path == PublicationPath.VERIFIED_NO_REVIEW
                else "HUMAN_PUBLISHED"
            )
            if view is not None and view != category:
                continue
            for post in revision.posts or [None]:
                fields = self._fields(master, post)
                readiness = master_post_readiness(self.session, revision, post)
                missing = list(readiness.missing)
                organisation = next(
                    (
                        fields[key].value
                        for key in (
                            "organisation.name",
                            "organization.name",
                            "organization.unit",
                            "department.name",
                        )
                        if key in fields
                    ),
                    None,
                )
                rows.append(
                    {
                        "public_id": post.public_id if post else master.id,
                        "authority_code": authorities[master.recruiting_authority_id].code,
                        "candidate_key": master.candidate_key,
                        "post_key": post.post_key if post else None,
                        "priority": "NONE",
                        "name": post.name if post else master.display_name,
                        "organisation": organisation or "Not specified",
                        "authority": authorities[master.recruiting_authority_id].name,
                        "vacancies": fields["vacancies.total"].value
                        if "vacancies.total" in fields
                        else None,
                        "closing_date": fields["application.end_date"].value
                        if "application.end_date" in fields
                        else None,
                        "path": category,
                        "verified_at": revision.verified_at,
                        "completeness": readiness.status.value,
                        "missing": missing,
                    }
                )
        return rows

    def detail(self, public_id: uuid.UUID) -> dict[str, Any]:
        master, post = self._current(public_id)
        revision = master.current_revision
        assert revision is not None
        source_revision = self.session.get(
            RecruitmentCandidateRevision, revision.source_candidate_revision_id
        )
        assert source_revision is not None
        extracted_fields = {}
        for candidate_field in self.session.scalars(
            select(CandidateField)
            .join(RecruitmentCandidateRevision)
            .where(
                RecruitmentCandidateRevision.recruitment_candidate_id
                == source_revision.recruitment_candidate_id
            )
            .order_by(RecruitmentCandidateRevision.revision_number)
        ):
            extracted_fields.setdefault(candidate_field.field_path, candidate_field)
        fields = self._fields(master, post)
        catalogue = []
        for scope, path, label, value_type in EDITABLE_FIELDS:
            if scope == "post" and post is None and path == "name":
                # Changing the identity of an unsplit Advertisement needs Post structuring.
                continue
            full_path = (
                path if scope == "shared" or post is None else f"posts.{post.post_key}.{path}"
            )
            field = fields.get(path)
            original = extracted_fields.get(full_path)
            catalogue.append(
                {
                    "path": full_path,
                    "label": label,
                    "value_type": value_type.value,
                    "value": _render(field.value) if field else "",
                    "original_value": _render(original.value) if original else "",
                    "source_locator": original.source_locator if original else None,
                    "origin": field.value_origin.value if field else "MISSING",
                }
            )
        readiness = master_post_readiness(self.session, revision, post)
        missing = list(readiness.missing)
        return {
            "public_id": public_id,
            "master_id": master.id,
            "master_revision_id": revision.id,
            "name": post.name if post else master.display_name,
            "publication_path": revision.publication_path.value,
            "source_url": source_revision.source_document.document_url,
            "source_document_id": source_revision.source_document_id,
            "candidate_revision_id": source_revision.id,
            "completeness": readiness.status.value,
            "missing": missing,
            "fields": catalogue,
            "structural_edit_url": f"/review/cases/{revision.review_case_id}"
            if revision.review_case_id
            else None,
        }

    def republish(
        self,
        public_id: uuid.UUID,
        expected_revision_id: uuid.UUID,
        changes: dict[str, str],
        reviewer: str,
        comment: str,
    ) -> bool:
        comment = comment.strip()
        if not comment or len(comment) > 8000:
            raise DomainConflictError("A reviewer comment of 1–8000 characters is required")
        master, focused_post = self._current(public_id, lock=True)
        current = master.current_revision
        assert current is not None
        if current.id != expected_revision_id:
            raise DomainConflictError("Published job changed; reload before editing")
        allowed = {
            path
            if scope == "shared" or focused_post is None
            else f"posts.{focused_post.post_key}.{path}": (
                scope,
                value_type,
            )
            for scope, path, _label, value_type in EDITABLE_FIELDS
            if focused_post is not None or path != "name"
        }
        if set(changes) - set(allowed):
            raise DomainConflictError(
                "Unsupported or structural field change; use Manual Post Builder"
            )
        current_fields = {field.field_path: field for field in current.fields}
        effective: dict[str, tuple[CandidateValueType, Any]] = {
            path: (field.value_type, field.value) for path, field in current_fields.items()
        }
        changed_paths = set()
        for path, raw in changes.items():
            if not raw.strip():
                continue  # Blank inputs do not erase published facts.
            value_type = (
                current_fields[path].value_type if path in current_fields else allowed[path][1]
            )
            if value_type != allowed[path][1]:
                raise DomainConflictError(
                    "Existing field type does not match the supported editor field"
                )
            try:
                parsed: Any = (
                    json.loads(raw)
                    if value_type == CandidateValueType.JSON
                    else (int(raw) if value_type == CandidateValueType.INTEGER else raw.strip())
                )
                parsed = normalize_typed_value(value_type, parsed)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                raise DomainConflictError(f"Invalid value for {path}: {error}") from error
            if path.endswith(("vacancies.total", "age.minimum", "age.maximum")) and (
                value_type == CandidateValueType.INTEGER and parsed < 0
            ):
                raise DomainConflictError(f"{path} cannot be negative")
            if path == "application.url" and (
                (url := urlparse(parsed)).scheme not in {"http", "https"} or not url.netloc
            ):
                raise DomainConflictError("Application URL must be an absolute HTTP(S) URL")
            if path.endswith(".name") and str(parsed).casefold().startswith("advertisement for"):
                raise DomainConflictError("Post title cannot be Advertisement prose")
            if path not in effective or effective[path][1] != parsed:
                effective[path] = (value_type, parsed)
                changed_paths.add(path)
        if not changed_paths:
            return False
        source = self.session.get(
            RecruitmentCandidateRevision, current.source_candidate_revision_id
        )
        if source is None or compute_persisted_revision_hash(source) != source.revision_hash:
            raise DomainConflictError("Current Candidate revision fails integrity validation")
        advertisement = source.advertisement_revision
        published_keys = {post.post_key for post in current.posts}
        if current.posts and (
            advertisement is None
            or not published_keys.issubset({post.post_key for post in advertisement.posts})
        ):
            raise DomainConflictError("Current Post structure is unavailable")
        shared = [
            CandidateFieldCreate(field_path=path, value_type=kind, value=value)
            for path, (kind, value) in effective.items()
            if not path.startswith("posts.")
        ]
        posts = []
        for post in current.posts:
            prefix = f"posts.{post.post_key}."
            organisation_paths = (
                "organisation.name",
                "organization.name",
                "organization.unit",
                "department.name",
            )
            previous_organisation = next(
                (
                    str(current_fields[prefix + path].value)
                    for path in organisation_paths
                    if prefix + path in current_fields
                ),
                "",
            )
            organisation = next(
                (
                    str(effective[prefix + path][1])
                    for path in organisation_paths
                    if prefix + path in effective
                ),
                "",
            )
            if (
                prefix + "organisation.name" in changed_paths
                and not previous_organisation
                and prefix + "name" not in changed_paths
            ):
                raise DomainConflictError(
                    "Add the base Post title when adding an organisation to a Post "
                    "whose previous organisation was not separately recorded"
                )
            facts = [
                CandidateFieldCreate(field_path=path.split(".", 2)[2], value_type=kind, value=value)
                for path, (kind, value) in effective.items()
                if path.startswith(prefix)
            ]
            title = next(
                (str(fact.value) for fact in facts if fact.field_path == "name"), post.name
            )
            name = canonical_post_name(
                title, organisation, previous_organisation=previous_organisation
            )
            if name != title:
                facts = [fact for fact in facts if fact.field_path != "name"]
                facts.append(
                    CandidateFieldCreate(
                        field_path="name", value_type=CandidateValueType.STRING, value=name
                    )
                )
                changed_paths.add(prefix + "name")
            posts.append(
                RecruitmentPostCreate(
                    post_key=post.post_key,
                    ordinal=post.ordinal,
                    name=name,
                    normalized_name=name.casefold(),
                    facts=facts,
                )
            )
        audit = json.dumps(
            {
                "operation": "PUBLISHED_JOB_MAINTENANCE",
                "master_revision": str(current.id),
                "candidate_revision": str(source.id),
                "post_key": focused_post.post_key if focused_post else None,
                "reviewer": reviewer,
                "changed": sorted(changed_paths),
                "submitted_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
        successor, created = CandidateService(self.session, commit=False).create_revision(
            source.recruitment_candidate_id,
            RecruitmentCandidateRevisionCreate(
                source_document_id=source.source_document_id,
                extraction_method="HUMAN_PUBLISHED_MAINTENANCE",
                extraction_note=audit,
                split_status=advertisement.split_status,
                split_note=advertisement.split_note,
                fields=shared,
                posts=posts,
            ),
        )
        if not created:
            raise DomainConflictError("Equivalent revision already exists; reload published job")
        links = CandidateFieldEvidenceRepository(self.session)
        for field in successor.fields:
            if field.field_path in changed_paths:
                continue
            prior = current_fields.get(field.field_path)
            if prior is None:
                continue
            prior_candidate = self.session.get(CandidateField, prior.source_candidate_field_id)
            if prior_candidate is None or prior_candidate.value != field.value:
                continue
            for evidence in links.list_evidence_for_field(prior_candidate.id):
                links.add(
                    CandidateFieldEvidence(
                        candidate_field_id=field.id,
                        evidence_id=evidence.id,
                        source_document_id=successor.source_document_id,
                    )
                )
        self.session.flush()
        verification = VerificationWorkerService(self.session).process_revision(successor.id)
        review = ReviewService(self.session, commit=False)
        case_id = verification.review_case_id
        confidence_id = verification.confidence_v2_assessment_id
        v1_confidence = self.session.get(
            RevisionConfidenceAssessment, verification.confidence_assessment_id
        )
        if v1_confidence is not None and v1_confidence.review_required:
            v1_case, _ = review.create_case(v1_confidence.id)
            v1_routes = {item.field_path_snapshot for item in v1_case.items}
            if changed_paths.issubset(v1_routes):
                if case_id is not None:
                    review.cancel_case(case_id)
                case_id = v1_case.id
                confidence_id = v1_confidence.id
            else:
                review.cancel_case(v1_case.id)
        if case_id is None:
            raise DomainConflictError("Changed values did not receive Human Review routing")
        case = review.start_case(case_id)
        routed_changes = {item.field_path_snapshot for item in case.items}
        if not changed_paths.issubset(routed_changes):
            raise DomainConflictError(
                "Changed values did not receive required Human Review routing"
            )
        for item in list(case.items):
            review.decide_item(
                item.id,
                ReviewDecisionCreate(
                    decision=ReviewDecisionType.APPROVE_AS_IS,
                    reviewer_identifier=reviewer,
                    decision_note=comment,
                    evidence_note=(
                        "Operator checked the official source; see maintenance audit note."
                    ),
                ),
            )
        MasterPublisherService(self.session, commit=False).publish(confidence_id)
        return True
