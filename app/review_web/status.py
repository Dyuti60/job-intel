"""Public-facing operational states; domain ReviewCase statuses remain unchanged."""

import enum


class ReviewPortalStatus(enum.StrEnum):
    ALL = "ALL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    AUTO_PUBLISHED = "AUTO_PUBLISHED"
    HUMAN_PUBLISHED = "HUMAN_PUBLISHED"
