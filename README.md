# Assam Job Intelligence

Foundation for a trustworthy master-data platform for Assam Government recruitment and job
information. The current implementation includes source, discovery provenance, candidate,
evidence, verification, confidence, and local Human Review capabilities.

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
to an untrusted network.

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

## APSC discovery worker

Run the narrow official APSC Advertisement 12/2026 discovery flow:

```text
uv run python -m workers.discovery --source APSC
```

Fetch and parse while rolling back database changes and skipping raw-file writes:

```text
uv run python -m workers.discovery --source APSC --dry-run
```

Raw bytes are content-addressed below `data/raw/` by default and referenced by portable `raw://`
URIs. Override the root with `AJI_RAW_STORAGE_ROOT`. HTTP limits are configurable with
`AJI_DISCOVERY_CONNECT_TIMEOUT_SECONDS`, `AJI_DISCOVERY_READ_TIMEOUT_SECONDS`,
`AJI_DISCOVERY_HTTP_RETRIES`, and `AJI_DISCOVERY_MAX_RESPONSE_BYTES`. The command exits 0 for a
successful or usable PARTIAL run and nonzero when discovery cannot safely execute. It creates no
Verification or Master data.

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

Run the supported APSC source through Discovery, Verification/Confidence/Review routing, and the
Master Publisher in one process:

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

## Trusted scheduled APSC pipeline

`.github/workflows/scheduled-pipeline.yml` runs the real one-shot APSC pipeline on the trusted
self-hosted Windows x64 runner. It supports manual dispatch (including dry-run) and a daily
02:30 UTC / 08:00 IST schedule. GitHub concurrency and the PostgreSQL advisory lock jointly prevent
overlap. The workflow upgrades Alembic first, records `GITHUB_ACTION` or `SCHEDULED` PipelineRun
trigger metadata, and publishes the CLI summary to the Actions job summary.

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
