from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_uses_hosted_runner_and_temporary_postgresql() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in workflow
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "postgres:17" in workflow
    assert "uv run alembic upgrade head" in workflow
    assert "uv run alembic check" in workflow
    assert "uv run pytest -q" in workflow
    assert "uv run ruff check ." in workflow
    assert "runner.temp" not in workflow


def test_scheduled_pipeline_has_trusted_boundaries_and_concurrency() -> None:
    workflow = (ROOT / ".github/workflows/scheduled-pipeline.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert 'cron: "30 2 * * *"' in workflow
    assert "runs-on: [self-hosted, Windows, X64]" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "D:\\ASSAM_JOB_DATA\\raw" in workflow
    assert "uv run alembic upgrade head" in workflow
    assert "workers.pipeline" in workflow
    assert "GITHUB_ACTION" in workflow
    assert "SCHEDULED" in workflow
    assert "uvicorn" not in workflow
    assert "PSExecutionPolicyPreference: Bypass" in workflow
    assert "shell: pwsh" not in workflow
    assert "permissions:\n  contents: read" in workflow
