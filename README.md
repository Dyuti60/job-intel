# Assam Job Intelligence

Foundation for a trustworthy master-data platform for Assam Government recruitment and job
information. The current implementation includes source, discovery provenance, candidate,
evidence, verification, confidence, and local Human Review capabilities.

The domain now distinguishes an Advertisement from its individual Posts. Historical
advertisement-level revisions are preserved as `LEGACY_UNSPLIT` and are never guessed into Posts;
new deterministic extractors can persist explicit Posts and PostFacts while retaining the existing
CandidateField-to-Evidence provenance chain.

The official archive family deterministically recognizes bounded vacancy/category tables and
post-wise qualification, age, experience, and pay tables. It emits Posts only for structurally
valid rows with exact totals; damaged splits and uncertain post ownership are retained as
evidence-backed ambiguity instead of guessed.

For a complete plain-language system walkthrough, local/browser startup guide, operator runbook,
debugging checklist, and handover map, see
[Knowledge Transfer and Operations Guide](docs/knowledge_transfer.md).

For a command-by-command setup, ingestion, Verification, Confidence, Human Review, and Master
publication guide with live local screenshots, see
[Complete Local Operations Runbook](docs/complete_operations_runbook.md).

## Local setup

1. Copy `.env.example` to `.env` and adjust local values if needed.
2. Run `uv sync`.
3. Run `docker compose up -d postgres`.
4. Run `uv run alembic upgrade head`.
5. Run `uv run uvicorn app.main:app --reload`.

The health endpoint is available at `GET /api/v1/health`.

## Local Human Review UI

Start the application after applying migrations:

```text
uv run uvicorn app.main:app --reload
```

Open `http://localhost:8000/review`. The server-rendered interface shows queued and in-progress
ReviewCases and reuses the existing T-008 lifecycle and decision services. It is intended only for
trusted localhost development. It has no authentication or CSRF protection and must not be exposed
to an untrusted network. After a case is started, the streamlined local form offers Approve or
Reject with one required comment. The audit identity comes from
`AJI_REVIEW_WEB_REVIEWER_IDENTIFIER` rather than being repeatedly entered in every item form.

## Master Publisher worker

Publish the next deterministic batch of eligible confidence/review results into Recruitment Master:

```text
uv run python -m workers.master_publisher
```

Inspect and validate pending work without changing Master data:

```text
uv run python -m workers.master_publisher --dry-run
```

`AJI_MASTER_PUBLISHER_BATCH_SIZE` controls the maximum pending assessments processed per execution
and defaults to 100. The worker exits 0 after a completed batch, including normal skips and isolated
domain/integrity failures that were reported per item. It exits nonzero for a worker-level failure
such as unusable configuration or database connectivity. The command is independently executable;
no recurring scheduler is included.

## Official-source discovery workers

Run one registered official Assam recruitment source:

```text
uv run python -m workers.discovery --source APSC
uv run python -m workers.discovery --source SLPRB_ASSAM
uv run python -m workers.discovery --source DEE_ASSAM
uv run python -m workers.discovery --source DME_ASSAM
```

Fetch and parse while rolling back database changes and skipping raw-file writes:

```text
uv run python -m workers.discovery --source APSC --dry-run
```

Raw bytes are content-addressed below `data/raw/` by default and referenced by portable `raw://`
URIs. Override the root with `AJI_RAW_STORAGE_ROOT`. HTTP limits are configurable with
`AJI_DISCOVERY_CONNECT_TIMEOUT_SECONDS`, `AJI_DISCOVERY_READ_TIMEOUT_SECONDS`,
`AJI_DISCOVERY_HTTP_RETRIES`, and `AJI_DISCOVERY_MAX_RESPONSE_BYTES`. The command exits 0 for a
successful or usable PARTIAL run and nonzero when discovery cannot safely execute. Archive adapters
select explicit official recruitment advertisements in an inclusive two-year lookback window (in
2026: calendar years 2024 through 2026). Past advertisements remain immutable history; result
lists, merit lists, appointment notices, and similar post-recruitment material are not treated as
separate recruitment identities. Discovery creates no Verification or Master data.

## Verification worker

Verify pending persisted APSC CandidateRevisions without fetching source websites:

```text
uv run python -m workers.verification --authority APSC
```

Preview the same workflow with no database changes:

```text
uv run python -m workers.verification --authority APSC --dry-run
```

Use `--candidate-key APSC_ADVT_12_2026` for an optional exact candidate target.
`AJI_VERIFICATION_BATCH_SIZE` bounds each oldest-first execution and defaults to 100. The worker
uses only persisted Evidence, queues Human Review where required, and never fetches sources, makes
review decisions, or invokes the Master Publisher.

## End-to-end pipeline

Run any supported source through Discovery, Verification/Confidence/Review routing, and the Master
Publisher in one process. Replace `APSC` with `SLPRB_ASSAM`, `DEE_ASSAM`, or `DME_ASSAM`:

```text
uv run python -m workers.pipeline --source APSC
```

Run all three established stage dry-runs without persistent changes:

```text
uv run python -m workers.pipeline --source APSC --dry-run
```

Every command invocation records a `PipelineRun` and per-stage operational history. This audit
record is the sole intentional write during `--dry-run`; source, candidate, verification, review,
and Master data remain unchanged. Inspect history through `GET /api/v1/pipeline-runs` and
`GET /api/v1/pipeline-runs/{id}`.

Queued or in-progress Human Review is a successful operational outcome, not an error. The pipeline
always invokes the Master Publisher, so a later execution can publish a ReviewCase resolved between
runs even when Discovery is unchanged and Verification has no new work. `SUCCESS` and usable
`PARTIAL` return exit code 0; fatal pipeline failures return nonzero.

The runtime command accepts `--trigger CLI`, `MANUAL`, `GITHUB_ACTION`, or `SCHEDULED` for its
operational audit. A source-scoped PostgreSQL advisory lock prevents overlapping local and Actions
executions; lock contention exits nonzero before domain or PipelineRun work starts.

## GitHub Continuous Integration

`.github/workflows/ci.yml` runs on pushes to `main`, pull requests targeting `main`, and manual
workflow dispatch. It uses a GitHub-hosted Ubuntu runner, Python 3.12, uv, and a disposable
PostgreSQL service database to apply the complete Alembic chain, check schema drift, run all tests,
and run Ruff. CI does not invoke live APSC Discovery and needs no runtime or production secrets.

Recommended flow: create a feature branch, push it, open a pull request to `main`, let CI pass, and
then merge. Repository administrators should enable branch protection for `main` and require the CI
job; this project does not alter repository protection settings automatically.

## Trusted scheduled official-source pipeline

`.github/workflows/scheduled-pipeline.yml` runs a real one-shot official-source pipeline on the
trusted self-hosted Windows x64 runner. Manual dispatch supports APSC, SLPRB Assam, DEE Assam, and
DME Assam (including dry-run). The daily 02:30 UTC / 08:00 IST schedule remains pinned to APSC;
additional schedules require an explicit operational decision. GitHub concurrency and the
PostgreSQL advisory lock jointly prevent overlap. The workflow upgrades Alembic first, records
`GITHUB_ACTION` or `SCHEDULED` PipelineRun trigger metadata, and publishes the CLI summary to the
Actions job summary.

Persistent configuration and raw files stay outside the disposable checkout under
`D:\ASSAM_JOB_DATA`. The workflow never serves or exposes the localhost Human Review interface and
does not bypass queued review. See [Trusted Windows pipeline runner](docs/self_hosted_runner.md) for
service installation, permissions, configuration, and validation.

## Local operational monitoring

Evaluate persisted pipeline history without contacting APSC:

```text
uv run python -m workers.monitoring --source APSC
uv run python -m workers.monitoring --source APSC --dry-run
```

The command deterministically reports current source health, recent per-stage duration trends,
queued Human Review workload, and bounded failure alerts. `--dry-run` predicts notification events
without storing or delivering them. Normal execution records deduplicated notification events and
routes them through the configured local channels (`LOG`, or `LOG,FILE`). File notifications must
use an external path such as `D:\ASSAM_JOB_DATA\notifications\events.jsonl`.

Run the application and open `http://localhost:8000/operations` for the private, read-only status
page. JSON clients can use `GET /api/v1/operational-status/{source_code}` and
`GET /api/v1/operational-notifications`. Like `/review`, this local administration surface has no
production authentication or CSRF boundary and must not be exposed publicly.

## Public Recruitment API

T-017 provides a read-only public contract sourced exclusively from ACTIVE RecruitmentMaster
records and each master's current immutable revision:

```text
GET /api/public/v1/recruitments
GET /api/public/v1/recruitments/{master_id}
```

The list supports `authority`, normalized `candidate_key`, literal text `q`, derived
`application_status`, application start/end ranges, vacancy ranges, deterministic `sort`, and
page-based pagination (`page_size` is capped at 100). Use optional `as_of=YYYY-MM-DD` for a
reproducible application-status view; otherwise status is evaluated on the current UTC date.

Responses include approved typed values and bounded source-document/endpoint provenance. They do
not expose drafts, historical non-current revisions, review decisions, confidence/verification
internals, evidence bodies, storage locations, operational history, or mutation operations. This is
the source of truth for the public browser interface.

## Public Recruitment website

After starting the application, open `http://localhost:8000/jobs`. The server-rendered interface
provides an accessible recruitment browse page, GET-only filters, deterministic pagination, and
approved recruitment detail pages with official-source links. It consumes the same T-017 public
read service and cannot query or mutate Candidate, Verification, Confidence, Review, monitoring,
or Publisher state.

The current live page is intentionally empty until at least one ReviewCase is resolved as
publishable and the Master Publisher creates an ACTIVE RecruitmentMaster. T-018 adds no JavaScript
framework, external CSS dependency, account system, eligibility matching, or public mutation API.
Approved historical recruitments remain visible and may derive a `CLOSED` application status from
their approved dates. Planned T-021 eligibility matching will operate only on approved Master data;
current ingestion does not infer that a past examination will recur.

## Confidence V2 and independent routing

New completed verification runs also produce immutable Confidence V2 assessments and a separate
Routing V1 assessment. V2 explains reliability from official provenance, extraction, support,
conflict, ambiguity, and completeness components; it does not approve, publish, or decide review.
Routing records semantic risks independently and never routes solely because an optional field is
absent. The existing publisher accepts V1 only until Post-aware Master support is introduced.

## Public release runtime

Production exposure must use the bounded public ASGI entry point, never `app.main`:

```text
uv run python -m workers.public_server
```

That process exposes only `/jobs`, `/api/public/v1`, `/static`, `/healthz`, and `/readyz`; internal
APIs plus `/review` and `/operations` are absent. Configure `AJI_PUBLIC_ALLOWED_HOSTS` with the real
hostname and trust forwarded headers only from the TLS reverse proxy through
`AJI_PUBLIC_FORWARDED_ALLOW_IPS`.

Build and run the hardened container locally behind a reverse proxy:

```text
docker compose -f docker-compose.public.yml build
docker compose -f docker-compose.public.yml up -d
uv run python scripts/public_release_smoke.py --base-url http://127.0.0.1:8001
```

The compose service binds only to loopback, runs as a non-root user with a read-only filesystem,
drops Linux capabilities, and expects a separately supplied read-only PostgreSQL URL. See
[Public deployment and recovery](docs/public_deployment.md) for database grants, TLS/proxy rules,
cache behavior, backup/restore, rollback, and release validation.

## Controlled public releases

T-020 selects the trusted Windows x64 runner with Docker Desktop as the V0 deployment host. The
manual **Public Release** workflow builds a commit-tagged image on a GitHub-hosted runner, blocks
fixable HIGH/CRITICAL vulnerabilities, publishes build
provenance, creates a coordinated external backup, and deploys through the protected
`public-production` environment by immutable SHA-256 digest. Caddy obtains managed TLS and routes only the bounded public
surface; the application container has no host port.

Configure the environment variables, secrets, approval protection, DNS, and runner prerequisites
in [Public deployment and recovery](docs/public_deployment.md) before selecting `deploy=true`.
The scheduled **Public Availability** workflow provides bounded external probes after activation.
The **Restore Rehearsal** workflow validates a selected database/raw snapshot in an isolated
temporary database and always removes that database afterward.
