import argparse
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

_CREDENTIAL_URL = re.compile(r"(\w+://)[^\s:/]+:[^\s@]+@")
_POSTGRES_IMAGE = (
    "postgres:17-alpine@sha256:"
    "18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
)


def _bounded_failure(result: subprocess.CompletedProcess[str]) -> str:
    message = (result.stderr or result.stdout or "pg_restore failed").splitlines()[0]
    return _CREDENTIAL_URL.sub(r"\1***:***@", message)[:500]


def _pg_restore_command(dump: Path, *arguments: str) -> list[str]:
    pg_restore = shutil.which("pg_restore")
    if pg_restore is not None:
        return [pg_restore, *arguments, str(dump)]
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("pg_restore or Docker is required on the trusted restore host")
    return [
        docker,
        "run",
        "--rm",
        "--volume",
        f"{dump.parent.resolve()}:/backup:ro",
        _POSTGRES_IMAGE,
        "pg_restore",
        *arguments,
        f"/backup/{dump.name}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Rehearse an isolated PostgreSQL/raw restore")
    parser.add_argument("--database-dump", required=True, type=Path)
    parser.add_argument("--raw-snapshot", required=True, type=Path)
    args = parser.parse_args()
    database_url = os.environ.get("AJI_RESTORE_ADMIN_DATABASE_URL", "")
    if not database_url:
        raise SystemExit("AJI_RESTORE_ADMIN_DATABASE_URL is required")
    if not args.database_dump.is_file() or not args.raw_snapshot.is_dir():
        raise SystemExit("Database dump and raw snapshot directory must both exist")
    check = subprocess.run(
        _pg_restore_command(args.database_dump, "--list"),
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0:
        raise SystemExit(_bounded_failure(check))

    source_url = make_url(database_url)
    rehearsal_name = f"aji_restore_{uuid.uuid4().hex[:12]}"
    admin_url = source_url.set(database="postgres", drivername="postgresql")
    restored_url = source_url.set(database=rehearsal_name, drivername="postgresql")
    restore_target = restored_url
    if shutil.which("pg_restore") is None and restored_url.host in {"localhost", "127.0.0.1"}:
        restore_target = restored_url.set(host="host.docker.internal")
    restored = False
    try:
        with psycopg.connect(
            admin_url.render_as_string(hide_password=False), autocommit=True
        ) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(rehearsal_name)))
        restore = subprocess.run(
            _pg_restore_command(
                args.database_dump,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                f"--dbname={restore_target.render_as_string(hide_password=False)}",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if restore.returncode != 0:
            raise RuntimeError(_bounded_failure(restore))
        with psycopg.connect(restored_url.render_as_string(hide_password=False)) as conn:
            revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            locations = conn.execute(
                "SELECT storage_uri FROM source_documents "
                "WHERE storage_uri LIKE 'raw://%' ORDER BY id LIMIT 1000"
            ).fetchall()
        if revision is None:
            raise RuntimeError("Restored database has no Alembic revision")
        missing = [uri for (uri,) in locations if not (args.raw_snapshot / uri[6:]).is_file()]
        if missing:
            raise RuntimeError(f"Raw snapshot is missing {len(missing)} referenced document(s)")
        restored = True
        print(
            f"Restore rehearsal passed at revision {revision[0]} with "
            f"{len(locations)} checked raw reference(s)"
        )
        return 0
    finally:
        with psycopg.connect(
            admin_url.render_as_string(hide_password=False), autocommit=True
        ) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(rehearsal_name)
                )
            )
        if not restored:
            print("Restore rehearsal failed; isolated database removed", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
