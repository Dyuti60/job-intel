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

## T-006 — Verification Runs and Field Verification

### Scope

Implement an independent, deterministic Verification domain for immutable candidate revisions and
fields. T-006 evaluates controlled persisted Evidence but does not implement numeric confidence,
Human Review, approval, master data, crawling, parsing, or LLM verification.

### Implementation summary

- Added PENDING/RUNNING/COMPLETED/PARTIAL/FAILED VerificationRuns with immutable revision-hash
  snapshots, derived field totals, service-managed result counters, failure metadata, and guarded
  transitions.
- Added pending/finalized FieldVerifications that snapshot field path, type, and structured value,
  then retain deterministic outcomes, reason codes, source-class counts, findings, and finalization
  time.
- Added SUPPORTS/CONTRADICTS/CONTEXT_ONLY VerificationEvidenceAssessments with normalized optional
  asserted values, derived source-class snapshots, cross-document verification support, and
  idempotent uniqueness.
- Implemented authoritative-conflict precedence, authoritative-support confirmation, baseline
  non-authoritative conflict detection, explicit insufficient-evidence reasons, and controlled
  NOT_APPLICABLE finalization without a numeric confidence score.
- Added conflict-transparent API responses containing evidence, source-document, endpoint, source
  class, locator, excerpt, assessment, asserted value, and note metadata.
- Preserved all candidate, extraction-evidence, Evidence, SourceDocument, and registry records;
  re-verification creates a separate run.

### Validation performed

- Dependency metadata did not change, so `uv sync` was not required for T-006.
- Existing development PostgreSQL began at `20260912_0005`, upgraded to
  `20260912_0006 (head)`, and passed `alembic check` with no model drift.
- Existing database downgrade from T-006 to T-005 and re-upgrade to T-006 passed.
- A separately named empty PostgreSQL database applied T-001 through T-006 in sequence, reported
  T-006 head, and passed `alembic check`; it was removed afterward.
- PostgreSQL inspection confirmed lifecycle/count checks, constrained vocabularies, restricted
  foreign keys, run/field and field/evidence uniqueness, JSONB snapshots, and intended indexes.
- Complete test suite: 150 passed in 10.71 seconds with two upstream dependency warnings.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors.

### Files created/changed

- Created: `alembic/versions/20260912_0006_verification_domain.py`,
  `app/models/verification.py`, `app/repositories/verification.py`,
  `app/schemas/verification.py`, `app/services/verification.py`,
  `app/api/v1/routes/verification.py`, `tests/test_verification_runs_api.py`,
  `tests/test_verification_assessments_api.py`,
  `tests/test_verification_outcomes_api.py`, and
  `tests/test_verification_persistence.py`.
- Changed: `app/models/evidence.py`, `app/models/__init__.py`,
  `app/api/v1/router.py`, `tests/factories.py`, `docs/architecture.md`,
  `docs/workflow.md`, `docs/task_log.md`, and `docs/next_task.md`.

### Test results

150 passed: 123 existing T-001 through T-005 tests and 27 T-006 tests covering run prerequisites,
lifecycle and snapshots; exact field scoping; assessment provenance, integrity, normalization and
idempotency; same-document, cross-document, and cross-source evaluation; every deterministic V0
outcome; authoritative precedence and conflict transparency; counters and completion policy;
immutability; re-verification; and database constraints.

### Known limitations

- Verification assessments are controlled structured inputs; T-006 does not interpret natural
  language or autonomously verify Evidence.
- Source class is snapshotted at assessment time, while other displayed provenance metadata is
  composed from retained Evidence, SourceDocument, and SourceEndpoint records.
- MULTI_SOURCE_SUPPORT is reserved in the reason vocabulary for a later policy; V0 confirmation
  requires authoritative-official support.
- T-006 persists no numeric confidence score, threshold, review decision, approval, or master data.
- Service/API immutability does not prevent privileged administrators from directly modifying the
  database outside normal application behavior.
- The current FastAPI/Starlette test-client stack continues to emit two upstream deprecation
  warnings.

## T-007 — Explainable Confidence Scoring and Review Routing

### Scope

Implement immutable, policy-versioned field and candidate-revision confidence assessments from
persisted T-006 Verification facts, with deterministic source weighting, criticality, aggregation,
explainable breakdowns, and review-routing metadata. T-007 does not create Human Review records,
approval, master data, crawling, or LLM scoring.

### Implementation summary

- Added immutable `FieldConfidenceAssessment` and `RevisionConfidenceAssessment` records with V1
  policy identity, score/coverage constraints, input-integrity hashes, JSONB explanations, review
  reasons, priorities, restricted foreign keys, and per-subject/policy uniqueness.
- Implemented V1 outcome anchors, distinct-SourceEndpoint support and contradiction modifiers,
  explicit caps, 0..100 clamping, and a maximum score of 25 for authoritative-conflict results.
- Centralized deterministic CRITICAL/STANDARD field-path classification and configurable standard,
  critical, and revision thresholds with defaults of 80, 90, and 85.
- Added deterministic field routing and weighted revision aggregation. CRITICAL fields have weight
  2, STANDARD fields weight 1, NOT_APPLICABLE is excluded from averaging, and verification coverage
  multiplies the weighted average. Partial verification and any field review condition survive
  aggregation.
- Added field- and run-scoped confidence calculation/retrieval APIs. POST calculation is idempotent:
  equivalent replay returns the original assessment, while a changed immutable-input fingerprint
  raises an integrity conflict.
- Preserved Verification, Evidence, candidate revision, and candidate field state; confidence
  calculation only appends T-007 assessment records.

### Validation performed

- Dependency metadata did not change, so `uv sync` was not required for T-007.
- Existing development PostgreSQL began at `20260912_0006`, upgraded to
  `20260912_0007 (head)`, and passed `alembic check` with no model drift.
- Existing database downgrade from T-007 to T-006 and re-upgrade to T-007 passed.
- A separately named empty PostgreSQL database applied T-001 through T-007 in sequence, reported
  T-007 head, and passed `alembic check`.
- PostgreSQL inspection confirmed JSONB explanations/reasons, restricted foreign keys, policy and
  routing vocabulary checks, score/coverage/count checks, per-policy uniqueness, and intended
  indexes.
- Complete test suite: 170 passed in 14.17 seconds with two upstream dependency deprecation
  warnings and one non-functional pytest cache-permission warning.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors; Git emitted informational LF-to-CRLF
  conversion warnings for existing Windows working-tree settings.

### Files created/changed

- Created: `alembic/versions/20260912_0007_confidence_scoring.py`,
  `app/models/confidence.py`, `app/repositories/confidence.py`,
  `app/schemas/confidence.py`, `app/services/confidence.py`,
  `app/services/confidence_policy.py`, `app/api/v1/routes/confidence.py`, and
  `tests/test_confidence_api.py`.
- Changed: `.env.example`, `app/core/config.py`, `app/models/__init__.py`,
  `app/api/v1/router.py`, `tests/test_config.py`, `docs/architecture.md`,
  `docs/workflow.md`, `docs/task_log.md`, and `docs/next_task.md`.

### Test results

170 passed: 150 existing T-001 through T-006 tests and 20 T-007 tests covering all anchors and
review routes; authoritative precedence; criticality; endpoint deduplication; deterministic input
ordering; threshold overrides; idempotent field/revision assessment; NOT_APPLICABLE exclusion;
weighted and coverage-adjusted aggregation; partial runs; low-critical-field masking prevention;
input immutability; and database score constraints.

### Known limitations

- V1 scores are deterministic reliability indicators, not statistically calibrated probabilities,
  eligibility percentages, approvals, or publication decisions.
- V1 criticality recognizes a documented baseline field-path set; unknown future paths default to
  STANDARD until a new policy version expands the classification contract.
- Thresholds are configuration-driven but are fingerprinted under V1. Changing thresholds after an
  assessment exists produces an integrity conflict for replay; historical rescoring requires a new
  policy version.
- Review reasons are enum-validated in application schemas/services and stored as JSONB arrays for
  multi-reason output; direct privileged database writes remain an administrative responsibility.
- T-007 records routing metadata only and creates no Human Review queue item or decision.
- The current FastAPI/Starlette test-client stack continues to emit two upstream deprecation
  warnings.

## T-008 — Human Review Queue and Decision Workflow

### Scope

Implement the persistent Human Review decision layer driven only by T-007 confidence routing,
including idempotent queue generation, field/revision work items, immutable reviewer decisions,
typed corrections, automatic case resolution, and an internal approved-projection preview. T-008
does not implement a browser UI, authentication, formal Master approval, or publication.

### Implementation summary

- Added QUEUED/IN_REVIEW/RESOLVED/CANCELLED `ReviewCase` records uniquely tied to a
  RevisionConfidenceAssessment, with revision/run references and immutable confidence score,
  policy, priority, reason, and component snapshots.
- Added deterministic FIELD and REVISION `ReviewItem` records. Every routed field produces one
  field item; PARTIAL_VERIFICATION and/or REVISION_SCORE_BELOW_THRESHOLD produce one consolidated
  revision item. Stable per-case item keys prevent duplicates.
- Added one immutable `ReviewDecision` per item with reviewer identity, decision/evidence notes,
  original value/type snapshots, normalized corrected values, and decision timestamps.
- Implemented APPROVE_AS_IS, field-only CORRECT_AND_APPROVE, REJECT, and
  REQUEST_REVERIFICATION rules. Corrections reuse T-004 value normalization, must preserve type,
  and must differ from the original CandidateField value.
- Added automatic resolution after the final item and deterministic outcome precedence:
  REVERIFICATION_REQUESTED, REJECTED, APPROVED_WITH_CORRECTIONS, then APPROVED.
- Added a non-persistent approved projection that includes original unrouted/approved values,
  substitutes reviewed corrections, and suppresses effective values for rejected/reverification
  cases.
- Strengthened T-007 replay integrity checks so ReviewCase generation verifies both confidence
  input fingerprints and deterministic persisted outputs before creating Human Review work.
- Added focused queue, lifecycle, item, decision, projection, filtering, ordering, idempotency,
  integrity, immutability, and database-constraint APIs/tests. No prior migration was modified.

### Validation performed

- Dependency metadata did not change, so `uv sync` was not required for T-008.
- Existing development PostgreSQL began at `20260912_0007`, upgraded to
  `20260912_0008 (head)`, and passed `alembic check` with no model drift.
- Existing database downgrade from T-008 to T-007 and re-upgrade to T-008 passed.
- A separately named empty PostgreSQL database applied T-001 through T-008 in sequence, reported
  T-008 head, and passed `alembic check`; it was removed afterward.
- PostgreSQL inspection confirmed lifecycle/snapshot checks, JSONB snapshots, review vocabularies,
  nonblank reviewer and required-note checks, corrected-value rules, restricted foreign keys,
  per-confidence/per-item uniqueness, and queue/reference indexes.
- Complete test suite: 191 passed in 31.08 seconds with two upstream dependency deprecation
  warnings and one non-functional pytest cache-permission warning.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors; Git emitted informational LF-to-CRLF
  conversion warnings for Windows working-tree settings.

### Files created/changed

- Created: `alembic/versions/20260912_0008_human_review.py`, `app/models/review.py`,
  `app/repositories/review.py`, `app/schemas/review.py`, `app/services/review.py`,
  `app/api/v1/routes/review.py`, `tests/test_review_api.py`, and
  `tests/test_review_persistence.py`.
- Changed: `app/models/__init__.py`, `app/repositories/confidence.py`,
  `app/services/confidence.py`, `app/api/v1/router.py`, `tests/factories.py`,
  `docs/architecture.md`, `docs/workflow.md`, `docs/task_log.md`, and
  `docs/next_task.md`.

### Test results

191 passed: 170 existing T-001 through T-007 tests and 21 T-008 tests covering review-required and
safe-confidence queue behavior; snapshot integrity and configuration stability; field/revision item
generation; queue ordering/filtering; lifecycle and cancellation; every decision type; required
identity/notes; typed correction normalization; replay idempotency; resolution and outcome
precedence; approved/rejected/reverification projections; the mandatory deadline correction;
historical immutability; and database uniqueness/check protection.

### Known limitations

- Reviewer identity is a bounded operator-provided string; authentication, authorization, and user
  records remain out of scope.
- Review work is not assigned to individual users, and T-008 provides no HTML or JavaScript UI.
- REQUEST_REVERIFICATION records intent only and does not create or execute another VerificationRun.
- The approved projection is an internal read preview, not formal approval, Recruitment Master, or
  a publication operation.
- Decisions are final in normal APIs. Changed judgment requires a new verification/confidence/review
  chain so historical decisions remain intact.
- Multi-reason snapshots are application-enum-validated JSONB arrays; direct privileged database
  writes remain an administrative responsibility.
- The current FastAPI/Starlette test-client stack continues to emit two upstream deprecation
  warnings.
