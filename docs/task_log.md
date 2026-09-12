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

## T-003 — Source Documents and Discovery Runs

### Scope

Implement persistent execution and raw-document provenance for the pipeline segment
`SourceEndpoint -> DiscoveryRun -> DiscoveryObservation -> SourceDocument`. T-003 performs no live
network fetching, parsing, recruitment extraction, candidate creation, Evidence creation, or
publishing.

### Implementation summary

- Added service-managed discovery runs with eligible-source enforcement, trigger metadata,
  constrained lifecycle, completion time, failure details, and observation counters.
- Added immutable source-document versions identified by endpoint, normalized URL, and canonical
  SHA-256 hash, with exact URL, HTTP/content metadata, first/latest run references, sighting times,
  status, and optional provider-neutral storage URI.
- Added run/document observations with deterministic NEW, UNCHANGED, and CHANGED classification,
  future UNAVAILABLE vocabulary, per-run HTTP metadata, and idempotent run/version association.
- Added explicit repositories, services, schemas, and operational APIs for starting/filtering/
  completing runs, recording/listing observations, and inspecting/filtering source documents.
- Added migration `20260912_0003` with restricted foreign keys, check/unique constraints, and
  query-oriented indexes.

### Validation performed

- Dependency metadata did not change, so `uv sync` was not required for T-003.
- Existing development database began at `20260912_0002`, upgraded to
  `20260912_0003 (head)`, and passed `alembic check`.
- Existing database T-003 downgrade to T-002 and upgrade back to T-003 passed after confirming the
  three T-003 tables contained zero rows.
- A separately named empty PostgreSQL database applied T-001, T-002, and T-003, reported T-003 head,
  and passed `alembic check`. The disposable database was removed afterward.
- PostgreSQL inspection confirmed all three T-003 tables, constrained vocabularies, completion and
  numeric checks, immutable-version and run/document uniqueness, restricted foreign keys, and
  intended indexes.
- Complete test suite: 53 passed in 1.83 seconds with two upstream dependency warnings.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors.

### Files created/changed

- Created: `alembic/versions/20260912_0003_discovery_provenance.py`,
  `app/models/discovery.py`, `app/repositories/discovery.py`,
  `app/schemas/discovery.py`, `app/services/discovery.py`,
  `app/api/v1/routes/discovery.py`, `tests/test_discovery_runs_api.py`,
  `tests/test_document_observations_api.py`, and
  `tests/test_discovery_persistence.py`.
- Changed: `app/models/source_registry.py`, `app/models/__init__.py`,
  `app/services/exceptions.py`, `app/api/v1/router.py`, `tests/factories.py`,
  `docs/architecture.md`, `docs/workflow.md`, `docs/task_log.md`, and
  `docs/next_task.md`.

### Test results

53 passed: 28 existing T-001/T-002 tests and 25 T-003 tests covering eligibility, run lifecycle,
failure details, filtering, deterministic hashing and classification, immutable versions, exact and
normalized URL behavior, distinct-URL identity, observation history, counters, payload validation,
document filtering, and database-level integrity.

### Known limitations

- T-003 accepts only bounded controlled text or a strictly validated SHA-256 hash; it is not a
  general upload or network-fetch API.
- Raw bytes are not stored in PostgreSQL. `storage_uri` is metadata only and no storage provider is
  integrated.
- UNAVAILABLE/document failure vocabularies prepare persistence for later fetchers; T-003's
  controlled observation service classifies only NEW, UNCHANGED, and CHANGED.
- Tests use isolated SQLite for API/service behavior and real PostgreSQL for migration/schema
  validation; SQLite does not preserve timezone offsets when round-tripping timestamps.
- The current FastAPI/Starlette test-client stack continues to emit two upstream deprecation
  warnings.

## T-004 — Recruitment Candidates and Extracted Fields

### Scope

Implement logical recruitment candidates, immutable structured revisions, and typed candidate
fields with exact SourceDocument provenance. All T-004 data remains unverified candidate data and
cannot enter Recruitment Master.

### Implementation summary

- Added authority-scoped candidate identity, DRAFT/READY_FOR_VERIFICATION/DISCARDED status, guarded
  forward-only transitions, and readiness requiring at least one structured revision.
- Added immutable, monotonically numbered candidate revisions originating from exactly one active
  SourceDocument version.
- Added deterministic SHA-256 revision identity over canonical source-document identity and sorted
  normalized field values. Exact replay reuses the revision; changed fields or source version create
  the next revision.
- Added CandidateFields with validated path identities, STRING/INTEGER/DECIMAL/BOOLEAN/DATE/
  DATETIME/JSON/NULL values, original raw text, source locators, and exact source-document
  references.
- Added service-level candidate/document authority validation and database-level composite
  revision/document provenance protection.
- Added explicit repositories, services, schemas, internal APIs, JSONB persistence, and migration
  `20260912_0004`.

### Validation performed

- Dependency metadata did not change, so `uv sync` was not required for T-004.
- Existing development database began at `20260912_0003`, upgraded to
  `20260912_0004 (head)`, and passed `alembic check`.
- Existing database T-004 downgrade to T-003 and upgrade back to T-004 passed after confirming all
  three T-004 tables contained zero rows.
- A separately named empty PostgreSQL database applied T-001 through T-004, reported T-004 head, and
  passed `alembic check`. The disposable database was removed afterward.
- PostgreSQL inspection confirmed candidate/revision/field tables, constrained vocabularies,
  authority/key, revision number/hash, and field path uniqueness, composite field provenance,
  restricted foreign keys, JSONB values, and intended indexes.
- Complete test suite: 101 passed in 4.46 seconds with two upstream dependency warnings.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors.

### Files created/changed

- Created: `alembic/versions/20260912_0004_recruitment_candidates.py`,
  `app/models/candidates.py`, `app/repositories/candidates.py`,
  `app/schemas/candidates.py`, `app/services/candidates.py`,
  `app/services/candidate_values.py`, `app/api/v1/routes/candidates.py`,
  `tests/test_recruitment_candidates_api.py`, `tests/test_candidate_revisions_api.py`,
  `tests/test_candidate_values.py`, and `tests/test_candidate_persistence.py`.
- Changed: `app/models/source_registry.py`, `app/models/discovery.py`,
  `app/models/__init__.py`, `app/api/v1/router.py`, `tests/factories.py`,
  `docs/architecture.md`, `docs/workflow.md`, `docs/task_log.md`, and
  `docs/next_task.md`.

### Test results

101 passed: 53 existing T-001 through T-003 tests and 48 T-004 tests covering candidate identity,
normalization, validation, filtering, status transitions, readiness, source consistency, immutable
revisions, replay idempotency, revision numbering and hashing, every supported field type,
canonical serialization, field collection/path validation, historical preservation, APIs, and
database constraints.

### Known limitations

- Candidate keys and structured fields must be provided by controlled callers; no parsing,
  extraction, OCR, or AI is implemented.
- READY_FOR_VERIFICATION means only workflow readiness and does not represent verification,
  confidence, approval, or truth.
- Revision identity intentionally excludes raw text, source locator, extraction method/note, and
  timestamps; replay preserves the first stored provenance metadata for that structured proposal.
- Revision immutability is enforced through append-only service/API behavior and the absence of
  mutation routes; direct privileged database access remains an administrative responsibility.
- Tests use isolated SQLite for API/service behavior and real PostgreSQL for migration/schema
  validation; SQLite does not preserve timezone offsets when round-tripping timestamps.
- The current FastAPI/Starlette test-client stack continues to emit two upstream deprecation
  warnings.

## T-005 — Candidate Evidence and Extraction Provenance

### Scope

Implement immutable, bounded extraction Evidence for unverified CandidateFields, including exact
SourceDocument provenance and idempotent many-to-many field associations. T-005 performs no
Verification, confidence scoring, authority weighting, review, publication, crawling, or parsing.

### Implementation summary

- Added immutable Evidence records with constrained extraction-provenance types, uninterpreted
  source locators, bounded excerpt/context, exact SourceDocument identity, and deterministic SHA-256
  hashes.
- Added explicit CandidateFieldEvidence associations supporting many fields per passage and many
  passages per field, with idempotent service behavior and database-enforced same-document
  provenance.
- Added Unicode NFC and line-ending normalization without collapsing meaningful internal
  whitespace; locators receive surrounding-whitespace normalization only.
- Added explicit repositories, services, schemas, focused internal APIs, migration
  `20260912_0005`, and comprehensive API, hashing, association, preservation, and persistence tests.
- Kept evidence attachment independent from candidate readiness and preserved CandidateRevision and
  CandidateField immutability.

### Validation performed

- Dependency metadata did not change, so `uv sync` was not required for T-005.
- Existing development PostgreSQL began at `20260912_0004`, upgraded to
  `20260912_0005 (head)`, and passed `alembic check` with no model drift.
- Existing database downgrade from T-005 to T-004 and re-upgrade to T-005 passed.
- A separately named empty PostgreSQL database applied T-001, T-002, T-003, T-004, and T-005 in
  sequence, reported T-005 head, and passed `alembic check`; it was removed afterward.
- PostgreSQL inspection confirmed evidence type/hash checks, document/hash and field/evidence
  uniqueness, same-document composite restricted foreign keys, and intended indexes.
- Complete test suite: 123 passed in 6.07 seconds with two upstream dependency warnings.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors.

### Files created/changed

- Created: `alembic/versions/20260912_0005_candidate_evidence.py`,
  `app/models/evidence.py`, `app/repositories/evidence.py`, `app/schemas/evidence.py`,
  `app/services/evidence.py`, `app/services/evidence_values.py`,
  `app/api/v1/routes/evidence.py`, `tests/test_evidence_api.py`,
  `tests/test_evidence_hashing.py`, `tests/test_candidate_field_evidence_api.py`, and
  `tests/test_evidence_persistence.py`.
- Changed: `app/models/candidates.py`, `app/models/__init__.py`,
  `app/repositories/candidates.py`, `app/api/v1/router.py`, `tests/factories.py`,
  `docs/architecture.md`, `docs/workflow.md`, `docs/task_log.md`, and `docs/next_task.md`.

### Test results

123 passed: 101 existing T-001 through T-004 tests and 22 T-005 tests covering Evidence creation,
retrieval and filtering, source eligibility, validation and bounds, normalization, deterministic
hash identity, idempotent replay, exact document-version separation, multi-field/multi-evidence
associations, same-document enforcement, historical preservation, and database constraints.

### Known limitations

- Evidence inputs come from controlled callers; T-005 does not fetch, parse, OCR, or extract source
  material.
- Excerpts and context are bounded provenance text, not raw-document storage; full artifacts remain
  behind SourceDocument's provider-neutral storage boundary.
- All evidence types require a nonblank excerpt in V0, including DOCUMENT_METADATA and OTHER.
- Evidence immutability is enforced by append-only service/API behavior and the absence of mutation
  routes; direct privileged database access remains an administrative responsibility.
- Evidence records do not establish truth, change candidate readiness, calculate confidence, or
  represent Verification.
- The current FastAPI/Starlette test-client stack continues to emit two upstream deprecation
  warnings.
