from contextlib import contextmanager

from app.services.pipeline_lock import PipelineAdvisoryLock, pipeline_advisory_lock_key
from workers import pipeline as pipeline_command


def test_pipeline_lock_key_is_stable_normalized_and_source_scoped() -> None:
    assert pipeline_advisory_lock_key("APSC") == pipeline_advisory_lock_key(" apsc ")
    assert pipeline_advisory_lock_key("APSC") != pipeline_advisory_lock_key("OTHER")
    assert -(2**63) <= pipeline_advisory_lock_key("APSC") < 2**63


def test_non_postgresql_test_database_does_not_claim_a_database_lock(db_session) -> None:
    lock = PipelineAdvisoryLock(db_session.get_bind(), "APSC")
    with lock.acquire() as acquired:
        assert acquired is True


def test_pipeline_cli_rejects_overlapping_source_before_history_or_domain_work(
    monkeypatch, capsys, db_session
) -> None:
    class DeniedLock:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        @contextmanager
        def acquire(self):
            yield False

    class ForbiddenHistory:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("history must not start without the source lock")

    @contextmanager
    def session_context():
        yield db_session

    monkeypatch.setattr(pipeline_command, "PipelineAdvisoryLock", DeniedLock)
    monkeypatch.setattr(pipeline_command, "PipelineHistoryService", ForbiddenHistory)
    monkeypatch.setattr(pipeline_command, "SessionLocal", session_context)

    assert pipeline_command.main(["--source", "APSC"]) == 2
    assert "overlap rejected" in capsys.readouterr().out.lower()
