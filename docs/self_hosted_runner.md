# Trusted Windows pipeline runner

The scheduled real APSC pipeline runs only on the repository's trusted Windows x64 self-hosted
GitHub Actions runner. Pull-request CI remains on GitHub-hosted Ubuntu and never receives access to
the persistent runtime database or raw documents.

## Install the runner as a Windows service

1. In GitHub, open **Settings → Actions → Runners → New self-hosted runner** for the repository.
2. Select Windows x64 and follow GitHub's current download and registration commands from an
   elevated PowerShell prompt. Treat the short-lived registration token as a secret; do not save it
   in this repository or paste it into logs.
3. Configure the runner name as `assam-job-intel-runner`, retain the standard `self-hosted`,
   `Windows`, and `X64` labels, and use a dedicated service account with the minimum required local
   access.
4. Run `svc install`, then `svc start`, from the runner directory. Confirm the service is running
   and the GitHub runner page reports **Online / Idle**.

The workflow targets labels rather than the runner name so the runner can be replaced without
changing application code. Only trusted maintainers should be able to modify or manually dispatch
the scheduled workflow. Never attach the self-hosted runner to workflows that execute untrusted
pull-request code.

The job uses the uv action and `uv python install 3.12`, which installs an isolated interpreter in
the runner service profile without requiring a machine-wide Python installation. PowerShell's
process execution policy is set to `Bypass` for generated workflow scripts only; it does not modify
the machine or user policy stored in the registry.

## Persistent runtime configuration

The checkout is disposable. Create these directories outside it:

```text
D:\ASSAM_JOB_DATA\config
D:\ASSAM_JOB_DATA\raw
```

Copy `.env.runner.example` to `D:\ASSAM_JOB_DATA\config\runtime.env` and place the real PostgreSQL
URL there. Restrict the file to administrators and the runner service identity. As an alternative,
set the repository Actions secret `AJI_DATABASE_URL`; the secret takes precedence over the external
file. Never use both as a way to switch databases silently—keep one documented source of truth.

The workflow always sets `AJI_RAW_STORAGE_ROOT=D:\ASSAM_JOB_DATA\raw`, validates that it is outside
`GITHUB_WORKSPACE`, applies `alembic upgrade head`, and then invokes the existing pipeline. If raw
documents already exist under an old checkout-local `data/raw` directory, copy that content into
the external root before the first scheduled run so existing `raw://` locations remain resolvable.

The runner service identity requires read access to the runtime configuration and modify access to
the raw-storage directory. It also needs network access to the registered official APSC endpoints
and database access. Do not grant it interactive administrator rights merely to run the workflow.

## Manual and scheduled execution

The **Trusted APSC Pipeline** workflow can be dispatched from the Actions page. Manual executions
are recorded with trigger `GITHUB_ACTION`; cron executions are recorded as `SCHEDULED`. The daily
schedule is `30 2 * * *` (02:30 UTC, 08:00 IST). A manual dry-run records PipelineRun operational
history but rolls back recruitment-domain changes.

GitHub Actions concurrency serializes workflow jobs for APSC. The CLI also takes a source-scoped
PostgreSQL session advisory lock, so a local CLI and an Actions job cannot overlap. Failure to
acquire the lock exits nonzero before creating a PipelineRun or changing domain data.

Human Review remains private. The workflow may queue ReviewCases and report them in its summary,
but it never starts the web server, exposes `/review`, or makes a review decision. Run the Review UI
only on the trusted local machine.

## Service checks

After installation or a service-account change, validate:

```text
uv run alembic current
uv run python -m workers.pipeline --source APSC --dry-run
```

Then manually dispatch the workflow and confirm its job summary contains the PipelineRun ID and
stage summary. Inspect `/api/v1/pipeline-runs` locally for the matching trigger and result. Rotate
database credentials through the external file or Actions secret; never commit them.
