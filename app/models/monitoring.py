import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.pipeline import PipelineRun
from app.models.source_registry import constrained_enum


class OperationalNotificationType(enum.StrEnum):
    PIPELINE_FAILED = "PIPELINE_FAILED"
    RUNNING_STALE = "RUNNING_STALE"
    SUCCESS_OVERDUE = "SUCCESS_OVERDUE"


class OperationalNotificationSeverity(enum.StrEnum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class OperationalNotificationChannel(enum.StrEnum):
    LOG = "LOG"
    FILE = "FILE"


class OperationalNotificationDeliveryStatus(enum.StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class OperationalHealthStatus(enum.StrEnum):
    HEALTHY = "HEALTHY"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STALE = "STALE"
    NO_DATA = "NO_DATA"


class OperationalNotificationEvent(Base):
    __tablename__ = "operational_notification_events"
    __table_args__ = (
        CheckConstraint(
            "length(deduplication_key) = 64 AND "
            "deduplication_key = lower(deduplication_key)",
            name="ck_operational_notifications_dedup_hash",
        ),
        CheckConstraint(
            "length(message) BETWEEN 1 AND 2000",
            name="ck_operational_notifications_message_length",
        ),
        CheckConstraint(
            "delivery_error IS NULL OR length(delivery_error) <= 2000",
            name="ck_operational_notifications_error_length",
        ),
        CheckConstraint(
            "(delivery_status = 'PENDING' AND delivered_at IS NULL AND delivery_error IS NULL) OR "
            "(delivery_status = 'DELIVERED' AND delivered_at IS NOT NULL "
            "AND delivery_error IS NULL) OR "
            "(delivery_status = 'FAILED' AND delivered_at IS NULL "
            "AND delivery_error IS NOT NULL)",
            name="ck_operational_notifications_delivery_shape",
        ),
        Index(
            "ix_operational_notifications_source_created",
            "source_code",
            "created_at",
        ),
        Index("ix_operational_notifications_event_type", "event_type"),
        Index("ix_operational_notifications_delivery_status", "delivery_status"),
        Index("ix_operational_notifications_pipeline_run_id", "pipeline_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT")
    )
    event_type: Mapped[OperationalNotificationType] = mapped_column(
        constrained_enum(
            OperationalNotificationType,
            "ck_operational_notifications_event_type",
        ),
        nullable=False,
    )
    severity: Mapped[OperationalNotificationSeverity] = mapped_column(
        constrained_enum(
            OperationalNotificationSeverity,
            "ck_operational_notifications_severity",
        ),
        nullable=False,
    )
    channel: Mapped[OperationalNotificationChannel] = mapped_column(
        constrained_enum(
            OperationalNotificationChannel,
            "ck_operational_notifications_channel",
        ),
        nullable=False,
    )
    deduplication_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    delivery_status: Mapped[OperationalNotificationDeliveryStatus] = mapped_column(
        constrained_enum(
            OperationalNotificationDeliveryStatus,
            "ck_operational_notifications_delivery_status",
        ),
        nullable=False,
    )
    delivery_error: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pipeline_run: Mapped[PipelineRun | None] = relationship()
