"""Shared, date-only recruitment lifecycle and deterministic operational ordering."""

import enum
from datetime import date, datetime
from zoneinfo import ZoneInfo


class JobLifecycle(enum.StrEnum):
    OPEN = "OPEN"
    RECENTLY_CLOSED = "RECENTLY_CLOSED"
    UPCOMING = "UPCOMING"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


def assam_today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _date(value: date | str | None) -> tuple[date | None, bool]:
    if value is None:
        return None, True
    if isinstance(value, date) and not isinstance(value, datetime):
        return value, True
    if isinstance(value, str):
        try:
            return date.fromisoformat(value), True
        except ValueError:
            pass
    return None, False


def classify_job(
    start: date | str | None,
    end: date | str | None,
    *,
    today: date,
    recently_closed_days: int,
) -> JobLifecycle:
    opening, valid_start = _date(start)
    closing, valid_end = _date(end)
    if not valid_start or not valid_end or (opening and closing and opening > closing):
        return JobLifecycle.UNKNOWN
    if opening and opening > today:
        return JobLifecycle.UPCOMING
    if closing is None:
        return JobLifecycle.UNKNOWN
    if closing >= today:
        return JobLifecycle.OPEN
    if (today - closing).days <= recently_closed_days:
        return JobLifecycle.RECENTLY_CLOSED
    return JobLifecycle.CLOSED


def lifecycle_sort_key(
    lifecycle: JobLifecycle,
    *,
    start: date | str | None,
    end: date | str | None,
    refreshed_at: datetime | None,
    stable_id: str,
) -> tuple[int, float, str]:
    opening, _ = _date(start)
    closing, _ = _date(end)
    rank = {
        JobLifecycle.OPEN: 0,
        JobLifecycle.RECENTLY_CLOSED: 1,
        JobLifecycle.UPCOMING: 2,
        JobLifecycle.CLOSED: 3,
        JobLifecycle.UNKNOWN: 4,
    }[lifecycle]
    if lifecycle == JobLifecycle.OPEN:
        within = float(closing.toordinal()) if closing else float("inf")
    elif lifecycle in {JobLifecycle.RECENTLY_CLOSED, JobLifecycle.CLOSED}:
        within = float(-closing.toordinal()) if closing else float("inf")
    elif lifecycle == JobLifecycle.UPCOMING:
        within = float(opening.toordinal()) if opening else float("inf")
    else:
        within = -refreshed_at.timestamp() if refreshed_at else float("inf")
    return rank, within, stable_id
