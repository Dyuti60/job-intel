# Task log

## T-001 — Project Foundation and Architecture Baseline

### Scope

Create the Python/FastAPI/PostgreSQL project foundation, architectural boundaries, governance rules,
development tooling, health endpoint, database/Alembic wiring, and foundational automated tests.
No recruitment domain tables or business capabilities are included.

### Implementation summary

- Added a Python 3.12 `uv` project with FastAPI, Pydantic Settings, SQLAlchemy 2, Alembic, HTTPX,
  Psycopg, Pytest, and Ruff.
- Added environment-driven configuration, basic structured logging context, application lifespan,
  a versioned health endpoint, and SQLAlchemy session infrastructure.
- Added Docker Compose PostgreSQL and an empty Alembic baseline wired to shared model metadata.
- Established package boundaries and permanent governance and architecture documentation.
- Added isolated tests for settings, application startup/metadata, health, and database connectivity.

### Validation performed

- `uv sync`: passed using CPython 3.12.14; 39 packages resolved and the project installed.
- Docker Compose PostgreSQL: image pulled and service reached `healthy`; `pg_isready` accepted
  connections. Host port 5432 was occupied, so validation used `POSTGRES_PORT=5433`.
- Alembic: `heads` and offline SQL generation passed. `upgrade head` passed against the clean
  Compose database and `current` reported `20260912_0001 (head)`.
- Live PostgreSQL connectivity: `SELECT 1` returned `1`.
- `alembic check`: passed with no new upgrade operations detected.
- Complete test suite: 6 passed.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors.

### Files created/changed

- Project/tooling: `.env.example`, `.gitignore`, `pyproject.toml`, `uv.lock`, `README.md`,
  `docker-compose.yml`, `alembic.ini`
- Governance/docs: `AGENTS.md`, `docs/architecture.md`, `docs/workflow.md`,
  `docs/task_log.md`, `docs/next_task.md`
- Application: `app/__init__.py`, `app/main.py`, `app/api/__init__.py`,
  `app/api/v1/__init__.py`, `app/api/v1/router.py`, `app/api/v1/routes/__init__.py`,
  `app/api/v1/routes/health.py`, `app/core/__init__.py`, `app/core/config.py`,
  `app/core/logging.py`, `app/db/__init__.py`, `app/db/base.py`, `app/db/session.py`,
  `app/models/__init__.py`, `app/repositories/__init__.py`, `app/schemas/__init__.py`,
  `app/schemas/health.py`, `app/services/__init__.py`
- Capability boundaries: `agents/__init__.py`, `agents/discovery/__init__.py`,
  `agents/verification/__init__.py`, `sources/__init__.py`,
  `sources/adapters/__init__.py`, `workers/__init__.py`, `review/__init__.py`
- Migrations/tests: `alembic/env.py`, `alembic/script.py.mako`,
  `alembic/versions/20260912_0001_foundation_baseline.py`, `tests/__init__.py`,
  `tests/test_config.py`, `tests/test_database.py`, `tests/test_health.py`

### Test results

6 passed in 0.52 seconds. Two dependency deprecation warnings were emitted by the current
FastAPI/Starlette test-client stack; no project test failed.

### Known limitations

- T-001 deliberately contains no recruitment domain tables or workflow implementation.
- The health endpoint reports process health only; database readiness is an infrastructure check.
- External source integrations and AI providers are not configured.
- Host port 5432 was already allocated during validation; this project's container was validated on
  configurable host port 5433.
- The current FastAPI/Starlette test-client dependency stack emits two upstream deprecation warnings.

## T-002 — Assam Source Registry

### Scope

Implement persistent trusted-source metadata for Assam recruiting authorities and their registered
web endpoints. T-002 does not fetch, crawl, parse, schedule, extract recruitment candidates, create
Evidence, verify claims, or publish master data.

### Implementation summary

- Added `RecruitingAuthority` with stable unique code, constrained authority type/status, official
  website URL, and timestamps.
- Added `SourceEndpoint` with restricted authority ownership, globally unique normalized URL,
  constrained endpoint type/class/status, independent discovery enablement, optional adapter key,
  last-verification time, provenance note, and timestamps.
- Added explicit repositories and service behavior, thin versioned API routes, conflict/not-found
  handling, list filters, pagination, controlled endpoint metadata updates, and status-only
  authority deactivation/reactivation.
- Added conservative HTTP/HTTPS URL normalization and application-plus-database duplicate defense.
- Added migration `20260912_0002` with foreign key, check constraints, unique constraints, and
  query-oriented indexes.

### Validation performed

- Dependency metadata did not change, so `uv sync` was not required for T-002.
- Existing development database began at `20260912_0001`, upgraded to
  `20260912_0002 (head)`, and passed `alembic check`.
- Existing database T-002 downgrade to T-001 and upgrade back to T-002 passed after confirming both
  registry tables contained zero rows.
- A separately named empty PostgreSQL database applied T-001 then T-002, reported T-002 head, passed
  `alembic check`, and passed a T-002 downgrade/upgrade cycle. The disposable database was removed
  afterward.
- PostgreSQL inspection confirmed both registry tables, named unique/check/foreign-key constraints,
  restricted authority deletion, and the intended endpoint indexes.
- Complete test suite: 28 passed in 0.45 seconds with two upstream dependency warnings.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors.

### Files created/changed

- Created: `alembic/versions/20260912_0002_assam_source_registry.py`,
  `app/models/source_registry.py`, `app/repositories/source_registry.py`,
  `app/schemas/source_registry.py`, `app/services/exceptions.py`,
  `app/services/source_registry.py`, `app/services/url_normalization.py`,
  `app/api/v1/routes/source_registry.py`, `tests/conftest.py`, `tests/factories.py`,
  `tests/test_source_authorities_api.py`, `tests/test_source_endpoints_api.py`, and
  `tests/test_source_registry_persistence.py`.
- Changed: `app/models/__init__.py`, `app/api/v1/router.py`,
  `docs/architecture.md`, `docs/workflow.md`, `docs/task_log.md`, and
  `docs/next_task.md`.

### Test results

28 passed: 6 existing T-001 tests and 22 T-002 tests covering authority and endpoint creation,
retrieval, listing, validation, 404/409 behavior, URL normalization, every required endpoint filter,
controlled updates, relationships, and database-level uniqueness.

### Known limitations

- No authorities or endpoints are seeded.
- Registry metadata does not prove a recruitment claim and is intentionally separate from future
  Evidence.
- Discovery eligibility is documented but no crawler, scheduler, or discovery execution exists.
- Tests use isolated SQLite for API/service behavior and real PostgreSQL for migration/schema
  validation; SQLite does not preserve timezone offsets when round-tripping timestamps.
- The current FastAPI/Starlette test-client stack continues to emit two upstream deprecation
  warnings.
