import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.review_routing import ReviewRoutingAssessment, ReviewRoutingPolicyVersion


class ReviewRoutingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, assessment: ReviewRoutingAssessment) -> None:
        self.session.add(assessment)

    def get_for_policy(
        self,
        revision_confidence_assessment_id: uuid.UUID,
        policy_version: ReviewRoutingPolicyVersion,
    ) -> ReviewRoutingAssessment | None:
        return self.session.scalar(
            select(ReviewRoutingAssessment).where(
                ReviewRoutingAssessment.revision_confidence_assessment_id
                == revision_confidence_assessment_id,
                ReviewRoutingAssessment.policy_version == policy_version,
            )
        )
