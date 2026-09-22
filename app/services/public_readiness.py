"""Deterministic public-facing minimum, independent of confidence and review policy."""

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.candidates import RecruitmentCandidateRevision, RecruitmentPost
from app.models.master import MasterPost, RecruitmentMasterRevision


class JobCompletenessStatus(enum.StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True)
class JobReadiness:
    status: JobCompletenessStatus
    missing: tuple[str, ...]


def evaluate_public_readiness(
    *,
    post_name: str | None,
    official_source_url: str | None,
    shared: Mapping[str, Any],
    post: Mapping[str, Any] | None,
) -> JobReadiness:
    """`post=None` is the genuine unsplit compatibility unit, never an explicit sibling."""
    facts = post if post is not None else shared

    def present(mapping: Mapping[str, Any], *paths: str) -> bool:
        return any(mapping.get(path) not in (None, "", [], {}) for path in paths)

    def shared_or_post(*paths: str) -> bool:
        return (
            present(facts, *paths)
            or present(shared, *paths)
            or present(shared, *(f"advertisement.{path}" for path in paths))
        )

    missing = []
    if not post_name or not post_name.strip():
        missing.append("Post name")
    if not official_source_url or not official_source_url.startswith(("https://", "http://")):
        missing.append("Official source")
    if not present(facts, "vacancies.total"):
        missing.append("Post vacancies")
    if not present(shared, "application.start_date"):
        missing.append("Opening date")
    if not present(shared, "application.end_date"):
        missing.append("Closing date")
    if not shared_or_post("qualification.minimum", "qualification.essential"):
        missing.append("Qualification")
    if not shared_or_post("age.minimum", "age.maximum"):
        missing.append("Age criteria")
    return JobReadiness(
        JobCompletenessStatus.PARTIAL if missing else JobCompletenessStatus.COMPLETE,
        tuple(missing),
    )


def candidate_post_readiness(
    revision: RecruitmentCandidateRevision, post: RecruitmentPost | None
) -> JobReadiness:
    shared = {
        field.field_path: field.value
        for field in revision.fields
        if not field.field_path.startswith("posts.")
    }
    facts = {fact.fact_key: fact.candidate_field.value for fact in post.facts} if post else None
    return evaluate_public_readiness(
        post_name=post.name if post else revision.recruitment_candidate.display_name,
        official_source_url=revision.source_document.document_url,
        shared=shared,
        post=facts,
    )


def master_post_readiness(
    session: Session, revision: RecruitmentMasterRevision, post: MasterPost | None
) -> JobReadiness:
    source = session.get(RecruitmentCandidateRevision, revision.source_candidate_revision_id)
    shared = {
        field.field_path: field.value
        for field in revision.fields
        if not field.field_path.startswith("posts.")
    }
    facts = {fact.fact_key: fact.master_field.value for fact in post.facts} if post else None
    return evaluate_public_readiness(
        post_name=post.name if post else revision.display_name,
        official_source_url=source.source_document.document_url if source else None,
        shared=shared,
        post=facts,
    )
