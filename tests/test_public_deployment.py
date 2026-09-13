from pathlib import Path

import pytest

from scripts.rehearse_restore import _bounded_failure

ROOT = Path(__file__).resolve().parents[1]


def test_public_image_applies_available_os_security_updates() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "apt-get update" in dockerfile
    assert "apt-get upgrade --yes --no-install-recommends" in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile


def test_release_compose_isolates_application_behind_tls_edge() -> None:
    compose = (ROOT / "docker-compose.release.yml").read_text(encoding="utf-8")
    caddy = (ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")

    assert (
        "caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
        in compose
    )
    assert '"80:80"' in compose and '"443:443"' in compose
    assert "public-web:" in compose and "expose:" in compose
    assert "public-web" not in compose.split("ports:", 1)[1].split("volumes:", 1)[0]
    assert "backend:\n    internal: true" in compose
    assert "read_only: true" in compose
    assert "cap_drop:" in compose
    assert "AJI_PUBLIC_DATABASE_URL" not in compose
    assert "@public path /jobs /jobs/* /api/public/v1/* /static/* /healthz /readyz" in caddy
    assert 'respond "Not Found" 404' in caddy
    assert "/review" not in caddy and "/operations" not in caddy and "/api/v1/" not in caddy
    assert "roll_size 10MiB" in caddy and "roll_keep 10" in caddy


def test_deployment_script_requires_immutable_image_and_rolls_back() -> None:
    script = (ROOT / "scripts/deploy_public_release.ps1").read_text(encoding="utf-8")
    assert "@sha256:[0-9a-f]{64}" in script
    assert "docker compose -f $ComposeFile pull" in script
    assert "public_release_smoke.py" in script
    assert "previousImage" in script
    assert "--force-recreate public-web" in script
    assert "releases.jsonl" in script
    assert "AJI_DATABASE_URL" in script
    assert "ConvertTo-Json -Compress" in script


def test_backup_script_keeps_coordinated_artifacts_outside_checkout() -> None:
    script = (ROOT / "scripts/create_runtime_backup.ps1").read_text(encoding="utf-8")
    assert "D:\\ASSAM_JOB_DATA\\backups" in script
    assert "D:\\ASSAM_JOB_DATA\\raw" in script
    assert "AJI_BACKUP_DATABASE_URL" in script
    assert "pg_dump --format=custom" in script
    assert "postgres:17-alpine@sha256:18cfe3ef" in script
    assert "Get-FileHash" in script
    assert 'Join-Path $destination "raw"' in script
    assert 'Join-Path $destination "manifest.json"' in script


def test_restore_rehearsal_has_digest_pinned_docker_fallback() -> None:
    script = (ROOT / "scripts/rehearse_restore.py").read_text(encoding="utf-8")
    assert "shutil.which(\"pg_restore\")" in script
    assert "shutil.which(\"docker\")" in script
    assert "18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73" in script
    assert "host.docker.internal" in script


def test_restore_failure_summary_is_single_line_and_bounded() -> None:
    class Result:
        stderr = "first failure\nsecret-looking later detail"
        stdout = ""

    assert _bounded_failure(Result()) == "first failure"

    Result.stderr = "x" * 700
    assert len(_bounded_failure(Result())) == 500

    Result.stderr = "failed postgresql://operator:topsecret@localhost/database"
    assert "topsecret" not in _bounded_failure(Result())


@pytest.mark.parametrize("missing", ["dump", "raw"])
def test_restore_rehearsal_rejects_missing_inputs(tmp_path, monkeypatch, missing) -> None:
    from scripts import rehearse_restore

    dump = tmp_path / "backup.dump"
    raw = tmp_path / "raw"
    dump.write_bytes(b"fixture")
    raw.mkdir()
    if missing == "dump":
        dump.unlink()
    else:
        raw.rmdir()
    monkeypatch.setenv("AJI_RESTORE_ADMIN_DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.setattr(
        "sys.argv",
        ["rehearse_restore.py", "--database-dump", str(dump), "--raw-snapshot", str(raw)],
    )

    with pytest.raises(SystemExit, match="must both exist"):
        rehearse_restore.main()
