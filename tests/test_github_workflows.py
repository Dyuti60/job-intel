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
    assert "docker build --tag assam-job-intelligence-public:ci ." in workflow
    assert "runner.temp" not in workflow


def test_scheduled_pipeline_has_trusted_boundaries_and_concurrency() -> None:
    workflow = (ROOT / ".github/workflows/scheduled-pipeline.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "- SLPRB_ASSAM" in workflow
    assert "- DEE_ASSAM" in workflow
    assert "- DME_ASSAM" in workflow
    assert "schedule:" in workflow
    assert 'cron: "30 2 * * *"' in workflow
    assert "runs-on: [self-hosted, Windows, X64]" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "D:\\ASSAM_JOB_DATA\\raw" in workflow
    assert "uv python install 3.12" in workflow
    assert "uv sync --frozen --python 3.12" in workflow
    assert "uv run alembic upgrade head" in workflow
    assert "workers.pipeline" in workflow
    assert "workers.monitoring" in workflow
    assert "AJI_MONITOR_NOTIFICATION_CHANNELS" in workflow
    assert "AJI_MONITOR_NOTIFICATION_FILE" in workflow
    assert "continue-on-error: true" in workflow
    assert "Preserve pipeline failure result" in workflow
    assert "$ErrorActionPreference = 'Continue'" in workflow
    assert "GITHUB_ACTION" in workflow
    assert "SCHEDULED" in workflow
    assert "uvicorn" not in workflow
    assert "PSExecutionPolicyPreference: Bypass" in workflow
    assert "shell: pwsh" not in workflow
    assert "actions/setup-python" not in workflow
    assert "permissions:\n  contents: read" in workflow


def test_public_release_builds_scans_attests_and_gates_deployment() -> None:
    workflow = (ROOT / ".github/workflows/public-release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "packages: write" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "id-token: write" in workflow
    assert "ghcr.io/dyuti60/job-intel-public" in workflow
    assert "sha-${GITHUB_SHA}" in workflow
    assert "github.ref != 'refs/heads/main'" in workflow
    assert "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25" in workflow
    assert "severity: HIGH,CRITICAL" in workflow
    assert "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in workflow
    assert "steps.push.outputs.digest" in workflow
    assert "@${{ needs.build.outputs.digest }}" in workflow
    assert "runs-on: [self-hosted, Windows, X64]" in workflow
    assert "environment:\n      name: public-production" in workflow
    assert "AJI_PUBLIC_DATABASE_URL" in workflow
    assert "AJI_BACKUP_DATABASE_URL" in workflow
    assert "create_runtime_backup.ps1" in workflow
    assert "deploy_public_release.ps1" in workflow
    assert "cancel-in-progress: false" in workflow


def test_public_availability_and_restore_workflows_are_bounded() -> None:
    availability = (ROOT / ".github/workflows/public-availability.yml").read_text(
        encoding="utf-8"
    )
    restore = (ROOT / ".github/workflows/restore-rehearsal.yml").read_text(encoding="utf-8")
    assert 'cron: "*/30 * * * *"' in availability
    assert "runs-on: ubuntu-latest" in availability
    assert "PUBLIC_BASE_URL" in availability
    for private_path in ("/review", "/operations", "/api/v1/health", "/docs", "/openapi.json"):
        assert private_path in availability
    assert "runs-on: [self-hosted, Windows, X64]" in restore
    assert "environment: public-production" in restore
    assert "AJI_RESTORE_ADMIN_DATABASE_URL" in restore
    assert "rehearse_restore.py" in restore
    assert "Restore inputs must remain outside" in restore
