# Public deployment and recovery

## Selected V0 target

The selected T-020 target is the existing trusted Windows x64 GitHub Actions runner with Docker
Desktop. `docker-compose.release.yml` runs the public application on an internal network and Caddy
as the only port-published edge. This is a single-host V0 deployment: keep the machine patched,
online, encrypted, and accessible only to trusted administrators.

Create a protected GitHub Environment named `public-production`, require maintainer approval, and
restrict deployment branches to `main`. Configure:

- variable `PUBLIC_HOSTNAME`: the DNS hostname, without a scheme or path;
- variable `PUBLIC_BASE_URL`: the matching `https://` origin;
- secret `AJI_PUBLIC_DATABASE_URL`: the least-privilege public reader URL;
- secret `AJI_BACKUP_DATABASE_URL`: the trusted runtime URL used only for pre-release backup;
- secret `AJI_RESTORE_ADMIN_DATABASE_URL`: an administrative URL used only by manual isolated
  restore rehearsals.

Point the hostname's DNS records at the host only after inbound TCP 80/443 reaches Docker Desktop.
No private application port should be forwarded. GitHub-hosted CI and image building never receive
any of these secrets.

## Separation model

Run `app.public_main:app` publicly. Never expose `app.main:app`: it contains the internal API,
Human Review, and operations pages. The supplied Compose file publishes the public container only
on `127.0.0.1:8001`; terminate TLS in a reverse proxy on the same trusted host or private network.
Forward only `/jobs`, `/api/public/v1`, `/static`, `/healthz`, and `/readyz` to that listener.

Set `AJI_PUBLIC_ALLOWED_HOSTS` to comma-separated exact deployment hosts. Set
`AJI_PUBLIC_FORWARDED_ALLOW_IPS` to only the reverse proxy address or trusted proxy CIDR; never use
`*` on an Internet-facing host. The proxy must replace, rather than append untrusted client
forwarding headers. Redirect HTTP to HTTPS and probe `/healthz` for liveness and `/readyz` for
database readiness.

## Least-privilege database role

Create a dedicated login with a generated secret through a secure operator channel. Adjust the
database/schema names when deployment differs:

```sql
CREATE ROLE aji_public_reader LOGIN PASSWORD '<generated-secret>';
GRANT CONNECT ON DATABASE assam_job_intelligence TO aji_public_reader;
GRANT USAGE ON SCHEMA public TO aji_public_reader;
GRANT SELECT ON TABLE
  public.recruitment_masters,
  public.recruitment_master_revisions,
  public.master_fields,
  public.master_posts,
  public.master_post_facts,
  public.candidate_fields,
  public.source_documents,
  public.source_endpoints,
  public.recruiting_authorities
TO aji_public_reader;
```

Do not grant INSERT, UPDATE, DELETE, sequence, migration, Candidate workflow, Evidence, Review,
Verification, Confidence, or operational-history access. Supply the resulting URL only through the
deployment environment or secret store; do not put it in Compose or source control.

## Build and release

1. Require a successful GitHub-hosted CI run on the exact commit.
2. Back up PostgreSQL and the external raw-content root as a coordinated recovery point.
3. Apply `uv run alembic upgrade head` from the trusted administrative runtime—not the public
   container.
4. Build an immutable, commit-tagged image: `docker build -t aji-public:<commit> .`.
5. Set the required `AJI_DATABASE_URL` and `AJI_PUBLIC_ALLOWED_HOSTS` outside the repository.
6. Start `docker compose -f docker-compose.public.yml up -d`.
7. Run `uv run python scripts/public_release_smoke.py --base-url http://127.0.0.1:8001`.
8. Confirm the reverse proxy serves HTTPS, HSTS, CSP, correct Host rejection, and no internal route.
9. Shift traffic to the new container and retain the prior image for rollback.

The public process does not run Alembic, Discovery, Verification, Review, or Publisher operations.

The preferred release is the manual **Public Release** workflow. First dispatch with `deploy=false`
to build, scan, push, and attest the exact commit. After reviewing that run, dispatch the same main
commit with `deploy=true`; the `public-production` approval gate pauses before the trusted host. The
host creates its coordinated backup, deploys, checks readiness and route isolation, and appends to
`D:\ASSAM_JOB_DATA\public-release\releases.jsonl`. Never weaken Environment approval to make a
failed deployment faster.

The image package may remain private: the deployment job logs into GHCR with its job-scoped token.
Grant no package token to pull-request workflows. Caddy's image is version-and-digest pinned.

## Credential rotation

Create a replacement PostgreSQL login with the same seven-table SELECT grants, update the protected
`AJI_PUBLIC_DATABASE_URL` secret, and run a deployment. Revoke the prior login only after readiness,
smoke, and an ordinary public read succeed. Rotation never changes the Publisher/runtime database
credential and never stores either URL in the checkout or release audit.

## Cache and request controls

`AJI_PUBLIC_CACHE_MAX_AGE_SECONDS` defaults to 60. Public content is rendered from the current
Master before conditional matching, and its body becomes a strong SHA-256 ETag. Keep reverse-proxy
caching configured to revalidate and honor `no-store`; do not configure a stale-if-error policy for
recruitment deadlines.

The release Compose keeps edge-to-application traffic on an internal backend network and gives only
the public application a separate database-access network. On the selected Docker Desktop host, a
host PostgreSQL URL must use `host.docker.internal`, not `localhost`; the latter would refer to the
application container itself. The public role remains read-only even though this network provides
the route to PostgreSQL.

The application defaults to 120 requests per 60 seconds per resolved client address and rejects
request targets over 4096 bytes. These are bounded V0 safeguards, not a distributed denial-of-
service service. Configure equivalent or stricter edge limits, connection limits, and access-log
retention at the reverse proxy.

## Backup and restore

Create encrypted, access-controlled, timestamped backups outside the application checkout:

```text
pg_dump --format=custom --file=<backup>/aji-YYYYMMDD-HHMM.dump assam_job_intelligence
robocopy D:\ASSAM_JOB_DATA\raw <backup>\raw /MIR /COPY:DAT /R:2 /W:2
```

Record the application commit, Alembic revision, database dump checksum, and raw-storage snapshot
identifier together. Test restore regularly into an isolated database and raw root:

```text
createdb assam_job_intelligence_restore_test
pg_restore --exit-on-error --clean --if-exists --dbname=assam_job_intelligence_restore_test <dump>
uv run alembic current
```

After restore, verify a sample `SourceDocument.storage_uri` resolves inside the restored raw root,
run the complete test suite against the isolated database, and perform the public smoke test. Never
overwrite the active database/raw root merely to test recovery.

The manual **Restore Rehearsal** workflow automates this validation. Supply matching absolute paths
under the external backup root. It uses local PostgreSQL client tools when available and otherwise
falls back to a digest-pinned PostgreSQL 17 utility container. It creates a random temporary
database, validates its Alembic revision and up to 1,000 `raw://` references, and removes the
database even when validation fails. Review its Actions record and retain the corresponding backup
manifest as release evidence.

## Rollback

For an application-only failure, route traffic back to the prior immutable image. T-019 has no
schema migration, so this rollback does not require a database downgrade. For later releases with
schema changes, confirm backward compatibility before traffic switching and use Alembic downgrade
only from a reviewed runbook after a verified backup. Data-loss recovery restores PostgreSQL and raw
storage from the same coordinated recovery point. Human Review, pipeline workers, and the Publisher
remain stopped until integrity and Alembic revision checks pass.

## Security limitations

The project does not provide authentication for the private application; network isolation remains
mandatory. The V0 public limiter is per process, no web-application firewall is included, and TLS
certificates are owned by the deployment proxy. Secrets, reviewer records, raw files, and private
operational APIs must never be mounted into or routed through the public container.

## Release checklist

- CI passes on the exact main commit.
- Build-only Public Release run passes vulnerability scanning and provenance attestation.
- DNS and protected Environment variables point to the reviewed target.
- The public database role has SELECT only on the documented tables.
- A coordinated backup and manifest exist outside the checkout.
- Protected deployment approval is recorded.
- `/healthz`, `/readyz`, `/jobs`, and the public API succeed over HTTPS.
- `/review`, `/operations`, `/api/v1`, `/docs`, and `/openapi.json` return 404 publicly.
- HSTS, CSP, ETag, and `must-revalidate` headers are present.
- The external release JSONL records the immutable image, prior image, actor, run, and time.
- The prior image remains available and a recent backup passes isolated restore rehearsal.
