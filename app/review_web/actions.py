"""Atomic private review actions composed through existing domain services."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.review import ReviewCase, ReviewCaseStatus, ReviewDecisionType, ReviewItemStatus
from app.schemas.review import ReviewDecisionCreate
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.master import MasterPublisherService
from app.services.review import ReviewService


class ReviewPublicationActions:
    def __init__(self, session: Session) -> None:
        self.session = session

    def quick(self, case_id: uuid.UUID, post_key: str, reviewer: str, comment: str) -> bool:
        """Approve pending values and publish one Post, or roll back every change."""
        if not comment.strip() or len(comment) > 8000:
            raise DomainConflictError("A reviewer comment of at most 8000 characters is required")
        with self.session.begin_nested():
            self.session.execute(
                select(ReviewCase).where(ReviewCase.id == case_id).with_for_update()
            )
            self.session.expire_all()
            review = ReviewService(self.session, commit=False)
            case = review.get_case(case_id)
            # This validates explicit Post ownership and returns immutable publication state.
            from app.review_web.services import ReviewCaseViewService

            view = ReviewCaseViewService(self.session).case(case_id, focus_post_key=post_key)
            if not view["focused_post"] or view["focused_post"]["key"] != post_key:
                raise DomainConflictError("A valid explicit Post is required")
            if view["publication"]["status"] == "PUBLISHED":
                return False
            relevant = [
                item
                for item in case.items
                if review._post_key(item.field_path_snapshot) in {None, post_key}
            ]
            if any(
                item.decision and item.decision.decision == ReviewDecisionType.REJECT
                for item in relevant
            ):
                raise DomainConflictError("An applicable review item has been rejected")
            pending = [item for item in relevant if item.status == ReviewItemStatus.PENDING]
            if pending:
                if case.status == ReviewCaseStatus.QUEUED:
                    review.start_case(case_id)
                review.submit_review_scope(
                    case_id,
                    post_key=post_key,
                    item_decisions={
                        item.id: ReviewDecisionCreate(
                            decision=ReviewDecisionType.APPROVE_AS_IS,
                            reviewer_identifier=reviewer,
                            decision_note=comment.strip(),
                        )
                        for item in pending
                    },
                    reviewer_identifier=reviewer,
                    decision_note=comment.strip(),
                    approve=True,
                )
            MasterPublisherService(self.session, commit=False).publish_post(
                case.revision_confidence_assessment_id,
                post_key,
            )
        return True

    def bulk(self, selections: list[tuple[uuid.UUID, str]], reviewer: str, comment: str) -> dict:
        if not selections or len(selections) > 50:
            raise DomainConflictError("Select between 1 and 50 Posts")
        if not comment.strip() or len(comment) > 8000:
            raise DomainConflictError("A reviewer comment of at most 8000 characters is required")
        result = {"published": 0, "already_published": 0, "blocked": []}
        for case_id, post_key in sorted(set(selections), key=lambda item: (str(item[0]), item[1])):
            try:
                published = self.quick(case_id, post_key, reviewer, comment)
                result["published" if published else "already_published"] += 1
            except (DomainConflictError, ResourceNotFoundError) as error:
                result["blocked"].append(f"{post_key}: {error}")
        self.session.commit()
        return result
