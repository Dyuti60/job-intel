import uuid

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.confidence import ReviewPriority
from app.models.review import (
    ReviewCase,
    ReviewCaseStatus,
    ReviewDecision,
    ReviewItem,
    ReviewItemStatus,
)


class ReviewCaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, review_case: ReviewCase) -> None:
        self.session.add(review_case)

    def get(self, case_id: uuid.UUID) -> ReviewCase | None:
        return self.session.scalar(
            select(ReviewCase)
            .execution_options(populate_existing=True)
            .options(
                selectinload(ReviewCase.items).selectinload(ReviewItem.decision),
                selectinload(ReviewCase.items).selectinload(ReviewItem.field_confidence_assessment),
            )
            .where(ReviewCase.id == case_id)
        )

    def get_by_confidence_assessment(self, assessment_id: uuid.UUID) -> ReviewCase | None:
        return self.session.scalar(
            select(ReviewCase).where(ReviewCase.revision_confidence_assessment_id == assessment_id)
        )

    def get_by_routing_assessment(self, assessment_id: uuid.UUID) -> ReviewCase | None:
        return self.session.scalar(
            select(ReviewCase).where(ReviewCase.review_routing_assessment_id == assessment_id)
        )

    def list(
        self,
        *,
        status: ReviewCaseStatus | None,
        priority: ReviewPriority | None,
        candidate_revision_id: uuid.UUID | None,
        verification_run_id: uuid.UUID | None,
        offset: int,
        limit: int,
    ) -> list[ReviewCase]:
        priority_order = case(
            (ReviewCase.priority == ReviewPriority.CRITICAL, 0),
            (ReviewCase.priority == ReviewPriority.HIGH, 1),
            (ReviewCase.priority == ReviewPriority.NORMAL, 2),
            else_=3,
        )
        statement: Select[tuple[ReviewCase]] = select(ReviewCase).order_by(
            priority_order, ReviewCase.opened_at, ReviewCase.id
        )
        if status is not None:
            statement = statement.where(ReviewCase.status == status)
        if priority is not None:
            statement = statement.where(ReviewCase.priority == priority)
        if candidate_revision_id is not None:
            statement = statement.where(ReviewCase.candidate_revision_id == candidate_revision_id)
        if verification_run_id is not None:
            statement = statement.where(ReviewCase.verification_run_id == verification_run_id)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


class ReviewItemRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: ReviewItem) -> None:
        self.session.add(item)

    def get(self, item_id: uuid.UUID) -> ReviewItem | None:
        return self.session.scalar(
            select(ReviewItem)
            .execution_options(populate_existing=True)
            .options(
                selectinload(ReviewItem.review_case),
                selectinload(ReviewItem.decision),
                selectinload(ReviewItem.field_confidence_assessment),
            )
            .where(ReviewItem.id == item_id)
        )

    def pending_count(self, case_id: uuid.UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count(ReviewItem.id)).where(
                    ReviewItem.review_case_id == case_id,
                    ReviewItem.status == ReviewItemStatus.PENDING,
                )
            )
            or 0
        )


class ReviewDecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, decision: ReviewDecision) -> None:
        self.session.add(decision)

    def get_for_item(self, item_id: uuid.UUID) -> ReviewDecision | None:
        return self.session.scalar(
            select(ReviewDecision).where(ReviewDecision.review_item_id == item_id)
        )

    def list_for_case(self, case_id: uuid.UUID) -> list[ReviewDecision]:
        return list(
            self.session.scalars(
                select(ReviewDecision)
                .join(ReviewDecision.review_item)
                .where(ReviewItem.review_case_id == case_id)
                .order_by(ReviewDecision.decided_at, ReviewDecision.id)
            )
        )
