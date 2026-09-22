from datetime import date

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.candidates import CandidateFieldCreate
from app.services.candidate_values import bound_raw_value


def test_history_window_settings_and_calendar_clamping(monkeypatch) -> None:
    monkeypatch.delenv("AJI_HISTORY_LOOKBACK_MONTHS", raising=False)
    assert Settings(_env_file=None).history_lookback_months == 12
    monkeypatch.setenv("AJI_HISTORY_LOOKBACK_MONTHS", "6")
    settings = Settings(_env_file=None)
    assert settings.history_cutoff(date(2026, 9, 22)) == date(2026, 3, 22)
    assert Settings(_env_file=None, history_lookback_months=12).history_cutoff(
        date(2026, 9, 22)
    ) == date(2025, 9, 22)
    assert Settings(_env_file=None, history_lookback_months=1).history_cutoff(
        date(2026, 3, 31)
    ) == date(2026, 2, 28)


@pytest.mark.parametrize("months", [0, 61])
def test_history_window_rejects_unbounded_values(months: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, history_lookback_months=months)


def test_raw_excerpts_bound_without_changing_typed_values() -> None:
    assert bound_raw_value("x" * 9_999) == "x" * 9_999
    assert bound_raw_value("x" * 10_000) == "x" * 10_000
    long_text = "x" * 12_000
    bounded = bound_raw_value(long_text)
    assert bounded == long_text[: 10_000 - len("...[truncated]")] + "...[truncated]"
    assert len(bounded) == 10_000
    field = CandidateFieldCreate(
        field_path="description.summary", value_type="STRING", value=long_text, raw_value=long_text
    )
    assert field.value == long_text
    assert field.raw_value == bounded
