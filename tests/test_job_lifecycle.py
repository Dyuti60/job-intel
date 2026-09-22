from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.job_lifecycle import JobLifecycle, classify_job, lifecycle_sort_key

TODAY = date(2026, 9, 22)


def test_lifecycle_boundaries_and_ordering() -> None:
    def classify(start, end, days=30):
        return classify_job(start, end, today=TODAY, recently_closed_days=days)
    assert classify(None, TODAY) == JobLifecycle.OPEN
    assert classify(TODAY - timedelta(days=1), TODAY + timedelta(days=1)) == JobLifecycle.OPEN
    assert classify(None, TODAY - timedelta(days=1)) == JobLifecycle.RECENTLY_CLOSED
    assert classify(None, TODAY - timedelta(days=30)) == JobLifecycle.RECENTLY_CLOSED
    assert classify(None, TODAY - timedelta(days=31)) == JobLifecycle.CLOSED
    assert classify(TODAY + timedelta(days=1), TODAY + timedelta(days=10)) == JobLifecycle.UPCOMING
    assert classify(None, None) == JobLifecycle.UNKNOWN
    assert classify("invalid", TODAY) == JobLifecycle.UNKNOWN
    assert classify(TODAY + timedelta(days=2), TODAY + timedelta(days=1)) == JobLifecycle.UNKNOWN

    rows = [
        (JobLifecycle.CLOSED, None, TODAY - timedelta(days=40), "closed"),
        (JobLifecycle.OPEN, None, TODAY + timedelta(days=10), "open-late"),
        (JobLifecycle.RECENTLY_CLOSED, None, TODAY - timedelta(days=2), "recent-old"),
        (JobLifecycle.OPEN, None, TODAY, "open-today"),
        (JobLifecycle.UPCOMING, TODAY + timedelta(days=1), None, "upcoming"),
        (JobLifecycle.RECENTLY_CLOSED, None, TODAY - timedelta(days=1), "recent-new"),
        (JobLifecycle.UNKNOWN, None, None, "unknown"),
    ]
    ordered = sorted(
        rows,
        key=lambda row: lifecycle_sort_key(
            row[0], start=row[1], end=row[2],
            refreshed_at=datetime(2026, 9, 22), stable_id=row[3],
        ),
    )
    assert [row[3] for row in ordered] == [
        "open-today", "open-late", "recent-new", "recent-old",
        "upcoming", "closed", "unknown",
    ]


def test_recent_close_setting_is_independent_of_history_window(monkeypatch) -> None:
    monkeypatch.delenv("AJI_RECENTLY_CLOSED_DAYS", raising=False)
    assert Settings(_env_file=None).recently_closed_days == 30
    monkeypatch.setenv("AJI_RECENTLY_CLOSED_DAYS", "6")
    assert Settings(_env_file=None).recently_closed_days == 6
    assert classify_job(None, TODAY - timedelta(days=7), today=TODAY,
                        recently_closed_days=6) == JobLifecycle.CLOSED
    for invalid in (0, 181):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, recently_closed_days=invalid)
