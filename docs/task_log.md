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

## T-011 — First Live Official Source Adapter: APSC

### Implementation summary

- Added conflict-safe idempotent APSC registry setup, bounded official-only HTTP, portal/feed/PDF
  adaptation, deterministic parsing, DD/MM/YYYY handling, pypdf, SHA-256 identities, OS trust-store
  TLS, and content-addressed `raw://` storage.
- Added a transactional one-shot worker with existing document classifications, Candidate/revision
  reuse, typed fields, exact-document Evidence, partial reporting, safe exits, summaries, and
  rollback-only dry-run. No migration was needed.
- Added fixture parser, HTTP retry/failure/limit, raw storage, idempotency, versioning, partial,
  provenance, dry-run, and no-truth-bypass tests.

### Validation performed

- Focused T-011 fixture tests: 11 passed.
- Complete regression suite: 236 passed in 34.12 seconds; Ruff passed.
- Live first run: all three official URLs returned HTTP 200; three NEW SourceDocuments,
  `APSC_ADVT_12_2026` revision 1, 14 fields, 14 Evidence links, SUCCEEDED, no Verification.
- Live second run: three UNCHANGED documents; Candidate and revision reused.
- Live dry-run: three UNCHANGED predictions; database counts remained two runs, three documents,
  one Candidate, one revision, 14 fields, nine shared Evidence records, zero VerificationRuns, and
  zero RecruitmentMasters.
- PostgreSQL joins traced registry through DiscoveryRun, PDF SourceDocument, Candidate, revision,
  fields, and Evidence links. The schema remained at `20260912_0009`.

### Known limitations

- The live WhatsNew feed is empty because Advertisement 12/2026 closed; the verified official PDF
  URL provides detailed extraction while portal/feed versions remain preserved.
- PDF parsing is narrow and text-only. Unsupported/image-only content is reported or omitted; no
  OCR, AI, third-party truth fallback, Verification, or publication is performed.

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

## T-009 — Local Human Review Web Interface

### Scope

Implement a minimal local server-rendered Human Review interface over the immutable T-008 review
domain. The interface presents queue, candidate, evidence, verification, confidence, decision,
resolution, and approved-projection information but creates no Recruitment Master or publication.

### Implementation summary

- Added FastAPI/Jinja2 pages at `/review` and `/review/cases/{case_id}`, isolated from `/api/v1`.
- Added a focused read-only `ReviewCaseViewService` that composes candidate/authority identity,
  source-document metadata, extraction Evidence, VerificationEvidenceAssessments, stored confidence
  components, review snapshots, progress, decisions, and the T-008 approved projection.
- Added operational queue counts, active-case priority/age ordering, status and priority filters,
  candidate/revision context, typed values, human-readable confidence breakdowns, review reasons,
  and visibly distinct supporting/contradicting assessments.
- Added POST-only start, cancel, and final-decision forms with Post/Redirect/Get behavior. All
  lifecycle, correction, idempotency, resolution, and projection behavior continues through
  `ReviewService`; templates contain no business decisions.
- Added STRING, INTEGER, DECIMAL, BOOLEAN, DATE, DATETIME, JSON, and documented NULL correction
  controls. Transport parsing hands typed input to the existing T-004/T-008 normalizer and does not
  duplicate domain normalization in JavaScript.
- Added resolved-decision and final-outcome displays plus master-eligibility-aware approved
  projection previews. CandidateField history remains unchanged after correction.
- Added local CSS, responsive layouts, escaped source context, safe new-window source links, and
  friendly HTML errors. No remote content is embedded or interpreted as HTML.
- Added Jinja2 3.1 as an explicit runtime dependency. T-009 introduced no database objects or
  migration.

### Validation performed

- `uv sync` completed after locking and installing Jinja2 3.1.6.
- Complete test suite: 201 passed in 24.91 seconds with two upstream dependency deprecation
  warnings.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors; Git emitted informational LF-to-CRLF
  conversion warnings for Windows working-tree settings.
- Existing development PostgreSQL reports `20260912_0008 (head)` and `alembic check` reports no new
  upgrade operations, confirming the presentation-only task added no migration.
- An isolated PostgreSQL database applied T-001 through T-008, then served the application through
  a real uvicorn process on localhost. End-to-end HTTP smoke validation passed queue loading, case
  visibility, start, readable extraction/verification Evidence, confidence explanation, safe
  source links, typed correction, automatic resolution, approved projection, and original
  CandidateField immutability. The temporary database was removed afterward.
- A graphical in-app browser was unavailable in the execution session, so the manual smoke used
  the real server and inspected rendered HTML over localhost HTTP rather than a visual browser.

### Files created/changed

- Created: `app/review_web/__init__.py`, `app/review_web/router.py`,
  `app/review_web/services.py`, `app/static/review.css`, `templates/review/base.html`,
  `templates/review/queue.html`, `templates/review/case.html`, `templates/review/error.html`, and
  `tests/test_review_web.py`.
- Changed: `app/main.py`, `pyproject.toml`, `uv.lock`, `README.md`, `docs/architecture.md`,
  `docs/workflow.md`, `docs/task_log.md`, and `docs/next_task.md`.

### Test results

201 passed: 191 existing T-001 through T-008 tests and 10 T-009 tests covering queue HTML,
ordering, filters and counts; candidate/confidence/reason/breakdown composition; field and revision
items; extraction and verification Evidence; supporting and contradicting provenance; source
links; escaped source text; read-only GET behavior; start/cancel; approve/correct/reject/reverify;
form errors; typed deadline correction; automatic resolution; approved/rejected/reverification
projection behavior; and CandidateField immutability.

### Known limitations

- The interface is localhost-only and has no authentication, authorization, CSRF protection,
  hardened sessions, reviewer assignment, or production deployment controls.
- Reviewer identifiers are entered separately in each decision form and persist only in the
  resulting ReviewDecision record.
- Source URLs are explicit links; their remote availability and safety are not checked by T-009.
- REQUEST_REVERIFICATION records intent only and does not start a new VerificationRun.
- The approved projection remains a read-only preview and is not approval, publication, or
  Recruitment Master.
- The execution environment exposed no connected graphical browser, so visual layout was covered
  by template assertions and real rendered-HTML HTTP smoke testing rather than interactive visual
  inspection.
- The current FastAPI/Starlette test-client stack emits two upstream deprecation warnings.

## T-010 — Approved Recruitment Master and Publisher

### Scope

Implement the canonical cleansed Recruitment Master and transactional deterministic Publisher over
eligible T-007 confidence and T-008 review results, without changing any prior pipeline history.

### Implementation summary

- Added logical RecruitmentMaster identity, an explicit current revision, immutable numbered
  RecruitmentMasterRevisions, typed MasterFields, field-level MasterChanges, and immutable
  MasterPublicationEvents.
- Added deterministic canonical SHA-256 projection identity over authority code, candidate key,
  display name, and sorted normalized typed fields.
- Added strict direct and Human Review publication eligibility, full candidate/verification/
  confidence/review integrity revalidation, and mandatory reuse of the T-008 approved projection
  for reviewed publication.
- Added corrected-value provenance from MasterField through ReviewDecision and CandidateField while
  leaving the original CandidateField unchanged.
- Added idempotent exact replay, unchanged-content reverification events, current-revision updates,
  last-verified refresh, and transactional ADDED/UPDATED/REMOVED change generation.
- Added internal Publisher and read APIs for masters, current state, revision history, fields,
  changes, and publication events.
- Added database and end-to-end tests for publication eligibility, both publication paths,
  corrections, hashing, idempotency, changed/unchanged projections, provenance, integrity,
  transaction rollback, reads, and uniqueness constraints.

### Validation performed

- Complete test suite: 217 passed in 25.86 seconds with two upstream dependency deprecation
  warnings.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors; Git emitted informational LF-to-CRLF
  conversion warnings for Windows working-tree settings.
- Existing PostgreSQL upgraded from `20260912_0008` to `20260912_0009`; `alembic current` reports
  `20260912_0009 (head)` and `alembic check` reports no new upgrade operations.
- T-010 downgraded to T-008 and re-upgraded successfully. A new empty PostgreSQL database applied
  the complete T-001 -> T-002 -> T-003 -> T-004 -> T-005 -> T-006 -> T-007 -> T-008 -> T-010
  chain successfully.
- PostgreSQL catalog inspection confirmed 47 named primary/foreign/unique/check constraints and 25
  indexes across the five T-010 tables, including restricted provenance FKs, current-revision FK,
  master identity, revision number/hash identity, field-path identity, change identity, and event
  idempotency.
- The controlled PostgreSQL scenario passed end to end: official and secondary Evidence,
  Verification, Confidence, Human correction from `2026-10-20` to `2026-10-27`, Master publishing,
  corrected provenance, and unchanged CandidateField history.
- The T-009 Review UI was served by uvicorn against the T-010 schema and `/review` returned HTTP
  200 with the queue page.

### Known limitations

- T-010 exposes an internal master contract only; public search, operational deadline status,
  eligibility, alerts, and live-source ingestion remain outside this task.
- Master display name is treated as business content and therefore participates in projection
  identity.
- Reusing an older identical projection resolves to the already immutable matching revision; the
  new provenance is retained in a publication event rather than duplicating business content.

## T-010B — Executable Master Publisher Worker

### Scope

Add an independently executable, bounded, idempotent PostgreSQL worker that discovers unpublished
RevisionConfidenceAssessments and delegates eligible items to the existing T-010
MasterPublisherService. T-010B adds no scheduler and no database objects.

### Implementation summary

- Added `python -m workers.master_publisher` with standard-library argument parsing, existing
  configuration/session/logging integration, concise operational summaries, and worker-level exit
  codes.
- Added an explicit deterministic repository query for assessments on COMPLETED VerificationRuns
  without a MasterPublicationEvent, ordered by creation time and UUID and bounded by
  `AJI_MASTER_PUBLISHER_BATCH_SIZE` (default 100).
- Added orchestration classification for direct, approved, corrected, missing/pending/cancelled
  review, rejected, and reverification-requested states. Only publishable states enter the existing
  T-010 Publisher.
- Added per-item rollback/failure isolation for domain and integrity errors while retaining
  worker-level failure for database/session outages.
- Added a read-only Publisher preview used by `--dry-run` to validate immutable inputs and predict
  create/update/unchanged behavior without Master mutations.
- Excluded already successfully processed assessments at query time, making an idle periodic rerun
  a no-op and preventing repeated UNCHANGED events for the same confidence input.
- Added focused orchestration, batch, ordering, skip, correction, replay, dry-run, CLI, exit-code,
  and configuration tests plus a controlled PostgreSQL smoke helper.

### Validation performed

- Complete test suite: 225 passed in 35.79 seconds with two upstream dependency deprecation
  warnings.
- Ruff: all checks passed.
- `git diff --check`: passed with no whitespace errors; Git emitted informational LF-to-CRLF
  conversion warnings for Windows working-tree settings.
- No migration was added. Existing PostgreSQL remains at `20260912_0009 (head)`, and
  `alembic check` reports no new upgrade operations.
- Controlled PostgreSQL first run scanned three assessments, published one VERIFIED_NO_REVIEW and
  one HUMAN_CORRECTED master, safely skipped one queued ReviewCase, and exited successfully.
- The Master API returned two records with two revisions, three fields, three initial changes, and
  two publication events; the corrected Master value was `2026-10-27` and the pending case remained
  unpublished.
- A second worker run skipped only the still-pending case and left all Master/revision/field/change/
  event counts unchanged.
- Dry-run discovered a new direct assessment, reported that one Master would be created, retained
  the pending-review skip, and left all Master counts unchanged.

### Known limitations

- T-010B is a one-shot command. Scheduling, distributed locks, Celery/Redis, and recurring
  orchestration remain out of scope.
- Old missing or pending review assessments remain discoverable on later runs. With a very small
  batch and a large permanently pending backlog, newer assessments can wait behind older items.
- Individual domain/integrity failures are reported but are not persisted as separate worker-run
  database records; logs and the command summary are the operational record for T-010B.
- The current FastAPI/Starlette test-client stack continues to emit two upstream deprecation
  warnings.

## T-012 — Automated Verification and Confidence Worker

### Result

- Added `python -m workers.verification` with required authority filtering, optional candidate-key
  targeting, `--dry-run`, deterministic oldest-first selection, configurable bounded batches, and
  per-revision transaction/failure isolation.
- Added a conservative no-network Evidence interpreter. It supports normalized exact STRING
  presence, field-labelled INTEGER values, and field-labelled DD/MM/YYYY, DD-MM-YYYY, and ISO DATE
  values. Ambiguous and unsupported evidence remains CONTEXT_ONLY.
- The worker uses CandidateService for DRAFT readiness, then existing Verification, Confidence,
  and Review services for every mutation. It finalizes all fields, computes V1 confidence, queues
  one idempotent ReviewCase where required, and stops before Human decisions or Master publishing.
- Completed V1 Verification/Confidence results suppress duplicate work. A resolved
  REVERIFICATION_REQUESTED case becomes eligible only until one newer run is created.
- Existing domain services gained opt-in flush-only units of work so the worker can commit or roll
  back a complete revision atomically without changing normal API commit behavior.
- Added five focused tests for typed support/contradiction/context behavior, DRAFT readiness,
  Confidence and Review integration, deterministic batching, replay idempotency, network isolation,
  one-shot reverification, and dry-run.

### Validation performed

- Complete test suite: 241 passed in 29.94 seconds; only upstream FastAPI/Starlette and local
  pytest-cache warnings were emitted.
- Ruff: all checks passed.
- No migration was added. PostgreSQL remained at `20260912_0009 (head)` and `alembic check`
  reported no new upgrade operations.
- Live T-011 APSC CandidateRevision `befd0911-2b8e-48e3-a9f1-526b45051a7d` produced VerificationRun
  `66bb7dd5-eb04-4006-9be4-badce5c7813f`: 14 total, 11 confirmed, 0 conflicted, 3 insufficient.
  V1 confidence was 83 and queued ReviewCase `d3569059-82ab-4d68-aa40-1dbaf7cc7405`.
- Dry-run predicted the same result and persisted nothing. An immediate second persisted execution
  scanned zero revisions; counts remained one run, one confidence assessment, and one ReviewCase.
- The localhost Review UI returned HTTP 200 and displayed the APSC key, score 83, and QUEUED state.
  RecruitmentMaster and MasterPublicationEvent counts remained zero.

### Known limitations

- Interpretation is intentionally narrow and not fuzzy or semantic. BOOLEAN, DATETIME, JSON, NULL,
  and unlabeled numeric/date assertions remain CONTEXT_ONLY.
- Worker failures are isolated and logged but no separate worker-run ledger is persisted.
- The in-app Browser runtime was unavailable during validation; review visibility was verified
  against the running local server with read-only HTTP requests instead.

## T-013 — End-to-End Pipeline Orchestrator

### Result

- Added `python -m workers.pipeline --source APSC` and `--dry-run` as a thin in-process coordinator
  over the existing APSC Discovery, Verification/Confidence/Review routing, and Master Publisher
  worker services.
- Added an explicit `APSC -> APSC` source/authority mapping and a structured PipelineSummary with
  per-stage summaries, active-review count, errors, and SUCCESS/PARTIAL/FAILED status.
- Preserved every stage transaction and policy boundary. Fatal Discovery short-circuits later
  stages; usable PARTIAL Discovery continues; queued review is SUCCESS; isolated downstream item
  failures make the combined result PARTIAL.
- The Master Publisher is always invoked after a safe Verification stage, including unchanged
  Discovery and zero new Verification work, allowing human-approved cases to publish later.
- Full dry-run delegates to each existing worker dry-run. It does not create a parallel simulation
  engine or persist source, candidate, verification, review, or master changes.
- Added nine focused tests covering direct publication, pending review, asynchronous correction and
  publication, rejection, one-shot reverification, changed and partial Discovery, fatal Discovery,
  idempotent replay, full dry-run, structured summaries, and CLI exit behavior.

### Validation performed

- Complete test suite: 250 passed in 38.76 seconds; only upstream FastAPI/Starlette and local
  pytest-cache warnings were emitted.
- Ruff: all checks passed.
- `git diff --check`: passed; only informational Windows LF-to-CRLF warnings were emitted.
- No migration was added. PostgreSQL remained at `20260912_0009 (head)` and `alembic check`
  reported no new upgrade operations.
- Live APSC pipeline run fetched the three bounded official resources with HTTP 200, classified all
  three SourceDocuments UNCHANGED, reused one Candidate and revision, processed zero Verification
  revisions, retained one active ReviewCase, skipped one pending-review publication, and returned
  SUCCESS with zero Master records.
- A second live run produced the same counts and no duplicate document version, candidate revision,
  VerificationRun, Confidence assessment, ReviewCase, Master, or publication event.
- Live dry-run reported the same route and preserved identical before/after counts: four historical
  DiscoveryRuns, three SourceDocuments, one CandidateRevision, one VerificationRun, one ReviewCase,
  and zero RecruitmentMasters.
- The controlled review-continuation test queued review on run one, corrected
  `application.end_date` from `2026-10-20` to `2026-10-27`, and published that corrected MasterField
  on an unchanged second run while preserving the CandidateField value.

### Known limitations

- T-013 supports only the explicit APSC mapping and remains a one-shot command without scheduling,
  overlap locking, or persistent pipeline-run history.
- `--candidate-key` is intentionally omitted because Discovery is currently one fixed APSC flow
  and the existing Master Publisher scans a global pending batch; partial propagation would give a
  misleading end-to-end targeting guarantee.
- Stage dry-runs are independent rollback simulations over persisted pre-stage state. Hypothetical
  Discovery output is not forwarded to Verification inside a shadow transaction.

## T-014 — Persistent Pipeline Run History and GitHub Actions CI

### Result

- Added `PipelineRun` and `PipelineStageRun` operational audit entities plus migration
  `20260912_0010`. Each CLI pipeline invocation records its trigger, overall/stage statuses,
  timestamps and durations, structured summaries, routing/publication counts, and bounded redacted
  failure details without duplicating T-013 orchestration logic.
- Updated the existing pipeline structured result with precise in-process stage executions. The CLI
  now wraps the same orchestrator with `PipelineHistoryService` and prints the operational run ID.
- Dry-run records only operational history; all established source, candidate, Verification,
  Confidence, Review, and Master rollback behavior remains unchanged.
- Added read-only newest-first `GET /api/v1/pipeline-runs` filtering and
  `GET /api/v1/pipeline-runs/{id}` stage-detail APIs.
- Added GitHub-hosted Ubuntu CI for pull requests to `main`, pushes to `main`, and manual dispatch.
  CI uses Python 3.12, frozen uv dependencies, a temporary PostgreSQL 17 service, the full Alembic
  chain/current/drift check, full Pytest, and Ruff with contents-read permission only.
- Added five focused test functions covering SUCCESS/PARTIAL/FAILED history, stage timing, summary
  retention, bounded credential-redacted errors, dry-run audit semantics, repeated operational
  runs, read APIs, filters, ordering, and missing IDs.

### Validation performed

- Complete test suite: 255 passed in 32.69 seconds; only upstream FastAPI/Starlette and local
  pytest-cache warnings were emitted.
- Existing PostgreSQL upgraded from `20260912_0009` to `20260912_0010`; `alembic current` reported
  head and `alembic check` reported no upgrade operations.
- T-014 downgraded cleanly to `20260912_0009` and re-upgraded to `20260912_0010`.
- A fresh PostgreSQL database applied T-001 through T-014 and passed current/drift checks. New
  indexes and all 17 primary/foreign/unique/check constraints were inspected in PostgreSQL.
- Local APSC pipeline smoke run completed SUCCESS with three timed stage rows: 2350 ms Discovery,
  18 ms Verification, and 12 ms Master Publisher. It retained one pending ReviewCase, produced no
  Master, and stored PipelineRun `0abc073a-0193-404a-aea0-a0468ae38e63`.
- A local dry-run stored a second operational history record while domain counts remained five
  DiscoveryRuns, three SourceDocuments, one CandidateRevision, one VerificationRun, one ReviewCase,
  and zero Masters.
- CI YAML parsed locally and its required trigger/service/step configuration was inspected. Remote
  GitHub Actions execution was not performed because no commit or push was authorized.

### Known limitations

- T-014 persists `RUNNING` state as groundwork but intentionally provides no overlap lock or
  scheduler. T-015 must combine application/database overlap protection with Actions concurrency.
- Pipeline history currently supports the explicit APSC source mapping inherited from T-013.
- Operational error text is bounded and connection credentials are redacted, but this is not a
  general-purpose secret-scanning system.

## T-015 — GitHub Actions Scheduled Pipeline Execution

### Result

- Added `.github/workflows/scheduled-pipeline.yml` for manual and daily APSC execution on the
  trusted `self-hosted`, `Windows`, `X64` runner. It uses contents-read permission, one non-cancelling
  APSC concurrency group, isolated uv-managed Python 3.12, frozen dependencies, Alembic upgrade,
  the existing T-013 CLI, and an always-rendered Actions job summary.
- Added `--trigger` to the pipeline CLI so manual Actions executions persist `GITHUB_ACTION` and
  cron executions persist `SCHEDULED` through the existing T-014 history service. CLI remains the
  default for ordinary local execution.
- Added a source-scoped `PipelineAdvisoryLock`. Its stable signed PostgreSQL bigint key is derived
  from SHA-256 of the normalized source identity. A dedicated connection holds the session advisory
  lock across Discovery, Verification, routing, Publisher, and PipelineRun finalization. Contention
  exits 2 before starting history or domain work.
- Kept hosted CI separate and repaired its invalid job-level `runner.temp` expression by using a
  fixed disposable Linux `/tmp` raw root. The config-default test now removes an ambient CI setting
  before asserting the application default.
- Established external runner state under `D:\ASSAM_JOB_DATA`: restricted runtime configuration in
  `config\runtime.env` and content-addressed raw files in `raw`. The three existing APSC raw objects
  were copied from checkout-local storage and their SHA-256 hashes matched.
- Added `.env.runner.example` without credentials and detailed Windows service installation,
  service-account permissions, persistent configuration, external storage, dispatch, lock, and
  private Review UI guidance in `docs/self_hosted_runner.md`.
- Added five focused tests for stable lock identity, SQLite test isolation, overlap rejection before
  history/domain work, Actions trigger persistence, hosted-CI boundaries, and trusted-workflow
  schedule/concurrency/storage/security configuration.

### Validation performed

- Complete local test suite: 260 passed in 34.85 seconds. Only upstream FastAPI/Starlette and local
  pytest-cache warnings were emitted.
- Ruff passed for the complete repository; `git diff --check` passed.
- Alembic remained at `20260912_0010` because T-015 adds no schema objects. Existing persistent
  PostgreSQL reported head and `alembic check` reported no upgrade operations.
- A fresh PostgreSQL database applied the complete T-001 through T-014 migration chain to
  `20260912_0010`; `alembic current` reported head and the drift check found no new operations.
- A real PostgreSQL overlap test held the APSC advisory key in a second session. The pipeline exited
  2, and PipelineRun count remained 3 before and after the rejected attempt.
- Hosted CI run `34722707313` completed successfully after applying the complete migration chain,
  checking drift, running all 260 tests, and Ruff. This also repaired the invalid T-014 CI workflow
  definition and its environment-dependent default-settings test.
- Trusted workflow run `34722717890` completed successfully on `assam-job-intel-runner`. It recorded
  GITHUB_ACTION PipelineRun `a24f62da-6474-4259-b1bb-8b659487e1f0` with three successful stage rows.
  Live Discovery found 3 UNCHANGED documents, Verification processed 0 revisions, the existing one
  queued ReviewCase remained active, Publisher skipped 1 pending-review assessment, and Master count
  remained 0.
- Trusted dry-run workflow `34722797952` completed successfully and recorded GITHUB_ACTION PipelineRun
  `18147b7d-22c8-4255-a487-81b651a3998f` with `dry_run=true`. PipelineRun history increased from 5
  to 6 while SourceDocument, CandidateRevision, VerificationRun, ReviewCase, and RecruitmentMaster
  counts remained exactly 3, 1, 1, 1, and 0.
- Repeated live Actions execution retained the same three SourceDocuments, one CandidateRevision,
  one VerificationRun, one ReviewCase, and zero Masters. No ReviewCase was started or decided.

### Known limitations

- The configured daily cron is 02:30 UTC / 08:00 IST. Manual `workflow_dispatch` and its trigger
  metadata were exercised remotely; a naturally elapsed cron event was not awaited during T-015.
- Only the explicit APSC source is scheduled. Adding another source requires a reviewed workflow
  mapping/concurrency key and corresponding persistent configuration.
- PostgreSQL advisory locking is the runtime overlap guarantee. SQLite intentionally bypasses the
  lock for isolated tests and is not a supported scheduled runtime database.
- The Review UI remains unauthenticated and localhost-only; the Actions workflow never starts or
  exposes it.

## T-016 — Operational Monitoring and Failure Notifications

### Result

- Added deterministic source health evaluation over existing PipelineRun/PipelineStageRun history,
  with explicit HEALTHY, RUNNING, DEGRADED, FAILED, STALE, and NO_DATA states. Stale RUNNING work,
  overdue success, latest failure/partial state, and recent per-stage duration trends are derived
  without mutating pipeline or recruitment domains.
- Added immutable `OperationalNotificationEvent` persistence with PIPELINE_FAILED, RUNNING_STALE,
  and SUCCESS_OVERDUE conditions; WARNING/CRITICAL severity; LOG/FILE local routing; delivery
  status; bounded redacted messages; and database-protected SHA-256 deduplication.
- Added `python -m workers.monitoring --source APSC [--dry-run]`. Dry-run predicts alerts without
  writes; normal execution records deduplicated delivery history. The trusted scheduled workflow
  now runs monitoring after every attempted pipeline and still preserves the original pipeline
  failure result.
- Added read-only `/api/v1/operational-status/{source_code}` and
  `/api/v1/operational-notifications` APIs plus the private `/operations` server-rendered page.
  These expose last-run health, queued review references, trends, and safe failure summaries without
  starting pipelines or exposing full operational payloads.
- Configured the trusted runner for optional append-only notifications at
  `D:\ASSAM_JOB_DATA\notifications\events.jsonl`, outside the Actions checkout, while keeping the
  Human Review and operations pages private/local.
- Added 12 new automated test functions (including parametrized cases), bringing the collected
  suite from 260 to 272 tests. Coverage includes status precedence, thresholds, duration trends,
  notification delivery/deduplication/failure, database uniqueness, safe APIs/HTML, dry-run,
  workflow integration, escaping, and domain immutability.

### Validation performed

- Complete local test suite: 272 passed in 35.43 seconds. Only upstream FastAPI/Starlette and the
  pre-existing inaccessible local pytest-cache warnings were emitted.
- Ruff passed for the complete repository; `git diff --check` passed.
- Existing persistent PostgreSQL upgraded from `20260912_0010` to `20260912_0011`, reported head,
  and Alembic detected no drift. T-016 downgraded cleanly to `0010`, then re-upgraded to `0011`
  with no drift.
- A fresh PostgreSQL database applied the full T-001 through T-016 chain to `20260912_0011`.
  Inspection found the expected primary/foreign/unique and eight named check constraints plus six
  indexes on `operational_notification_events`.
- Local live-state smoke checks reported APSC HEALTHY, three stage trends, one queued ReviewCase,
  and zero alert events. Both dry-run and normal monitoring completed successfully; the read-only
  API returned HTTP 200 and the operations page rendered HTTP 200.
- GitHub-hosted CI run `34723884746` completed successfully for commit `ee73aed`, including fresh
  migration, drift check, the full suite, and Ruff.
- Trusted workflow run `34723971833` completed successfully on `assam-job-intel-runner`; database
  upgrade, live pipeline, monitoring, and summary steps all passed. Live Discovery observed three
  unchanged documents, Verification found no new revision, Publisher skipped the existing pending
  review, the APSC ReviewCase remained QUEUED, and Master count remained zero.

### Known limitations

- T-016 routes notifications only to local logging and optional local JSONL. Email, SMS, chat, and
  hosted observability integrations are intentionally absent.
- Health is evaluated when the monitoring worker/API/page is invoked; there is no independent
  always-on monitoring daemon. The scheduled Actions workflow provides the current recurring check.
- The private operations and Review pages have no production authentication/authorization or CSRF
  hardening and must remain bound to a trusted local environment.
- Stage trends are bounded descriptive summaries, not anomaly detection or a distributed metrics
  platform.

## T-017 — Public Recruitment Read API and Search Baseline

### Result

- Added a separate read-only `/api/public/v1` namespace with list and detail endpoints for Assam
  Government recruitments. Public selection starts exclusively from ACTIVE RecruitmentMaster rows
  and requires the selected current revision to belong to that same master.
- Added bounded page responses (maximum 100 records), normalized authority/candidate filters,
  escaped literal text search, application start/end ranges, vacancy ranges, deterministic sorting,
  and stable UUID tie-breaks.
- Added read-time UPCOMING, OPEN, CLOSED, and UNKNOWN application status derived only from approved
  DATE fields. Boundaries are inclusive, an optional `as_of` date makes results reproducible, and
  no Master history is rewritten.
- Added safe public summary/detail schemas. Detail exposes current approved typed fields and bounded
  source URL/document/endpoint/source-class/authority provenance, while excluding candidate IDs,
  Evidence bodies, Review decisions, Verification/Confidence internals, hashes, raw storage,
  historical revisions, changes, publication events, and operational history.
- Kept the existing internal Master and publisher APIs unchanged. The public namespace contains GET
  operations only and T-017 adds no database schema, public HTML UI, or mutation path.
- Added seven end-to-end API tests covering the approved contract, source provenance, inactive and
  unpublished isolation, unresolved/rejected review isolation, historical revision exclusion,
  fail-closed current-pointer integrity, filters, ordering, pagination, date boundaries, literal
  search escaping, validation bounds, GET-only OpenAPI methods, and database immutability.

### Validation performed

- Complete local test suite: 279 passed in 110.56 seconds. Only upstream FastAPI/Starlette and the
  pre-existing inaccessible local pytest-cache warnings were emitted.
- Ruff passed for the complete repository; `git diff --check` passed.
- T-017 required no migration or dependency change. Existing persistent PostgreSQL remained at
  `20260912_0011 (head)` and `alembic check` reported no schema drift.
- A fresh PostgreSQL database applied the complete T-001 through T-016 migration chain to
  `20260912_0011`; current and drift checks passed. No T-017 database object was introduced.
- The live public list returned HTTP 200 with an empty bounded page. This is the correct trusted
  result because the real APSC CandidateRevision still has a QUEUED ReviewCase and no
  RecruitmentMaster exists. OpenAPI inspection exposed exactly the two public paths with GET only.
- GitHub-hosted CI run `34742634100` completed successfully for implementation commit `4956c19`,
  including fresh PostgreSQL migration, Alembic drift checking, the full test suite, and Ruff.

### Known limitations

- The public contract currently has no browser interface; T-018 will consume it with a minimal
  server-rendered public experience.
- Selected structured date/vacancy filtering is performed after the authority/identity/text query
  for the V0 Assam-sized dataset. A future scale milestone may promote these approved fields into a
  dedicated indexed read projection without weakening the Master-only boundary.
- Deployment-layer TLS, rate limiting, cache headers/CDN behavior, abuse controls, and production
  hosting remain outside this local repository milestone.
- The public API will remain empty for the live APSC record until a human resolves its existing
  ReviewCase and the Master Publisher successfully creates an ACTIVE RecruitmentMaster.

## T-018 — Public Recruitment Web Interface

### Result

- Added a public, server-rendered `/jobs` browse page over the T-017 read service with deterministic
  authority, application-status, closing-date, vacancy, text, ordering, and pagination controls.
  Filter validation remains in the shared read service so the HTML and JSON transports enforce the
  same approved-data contract.
- Added `/jobs/{master_id}` recruitment detail pages showing current approved Master fields,
  derived application state, authority and candidate identity, last-verified metadata, and safe
  links to registered source documents. Internal candidate, verification, confidence, review,
  publisher, and operational records are not exposed.
- Added a focused presentation composition service that accepts only T-017 public DTOs. Templates
  contain no database queries or business decisions, and every public web route is read-only.
- Added local Jinja templates, CSS, and a favicon with responsive single-column behavior, keyboard
  focus states, a skip link, semantic landmarks, explicit empty/error states, canonical local URLs,
  and no JavaScript framework, CDN, iframe, or external asset dependency.
- Added six end-to-end web tests covering empty and filtered lists, stable pagination, approved
  detail/provenance rendering, inactive and unpublished isolation, output escaping, and proof that
  GET rendering does not mutate domain data and that no POST mutation route exists.

### Validation performed

- Complete local test suite: 285 passed in 40.39 seconds. Only upstream FastAPI/Starlette and the
  pre-existing inaccessible local pytest-cache warnings were emitted.
- Ruff passed for the complete repository; `git diff --check` passed.
- T-018 required no dependency or migration change. The configured local PostgreSQL database was
  recreated after it was found absent, the complete migration chain applied successfully through
  `20260912_0011 (head)`, and `alembic check` reported no schema drift.
- Local HTTP smoke testing returned HTTP 200 for `/jobs` and its stylesheet. The empty state was the
  correct trusted result for the available local database because no ACTIVE RecruitmentMaster was
  present.
- Desktop and narrow-width pages were rendered and visually inspected with Microsoft Edge in
  headless mode. Layout, navigation, filters, empty state, and responsive single-column behavior
  rendered cleanly. The interactive computer-use browser was unavailable in this environment, so
  no claim is made for an interactive browser session.

### Known limitations

- The public website intentionally remains empty until approved RecruitmentMaster data exists; it
  never falls back to Candidate, queued ReviewCase, or discovery data.
- T-018 is a local presentation milestone. Production network separation, authentication of private
  administration surfaces, TLS/forwarded-host hardening, rate limiting, security headers, cache
  policy, deployment packaging, and release smoke tests remain for T-019.
- Search and structured filtering retain the T-017 V0 in-process projection behavior, which is
  appropriate for the initial Assam-sized dataset but is not a large-scale search index.

## T-019 — Public Release Hardening and Deployment Baseline

### Result

- Added `app.public_main` as a separate production composition root. It exposes only `/jobs`,
  `/api/public/v1`, `/static`, `/healthz`, and `/readyz`; internal `/api/v1`, `/review`,
  `/operations`, OpenAPI, and documentation routes are absent rather than hidden by UI convention.
- Added trusted-host enforcement, production wildcard-trust rejection, configured forwarded-proxy
  trust, bounded request-target size, a bounded in-memory fixed-window request limiter, and CSP,
  framing, MIME-sniffing, referrer, opener/resource, permissions, and HTTPS-only HSTS headers.
- Added SHA-256 response ETags with short `must-revalidate` caching. Conditional requests compare
  against a freshly rendered current-Master representation, preventing a superseded Master revision
  from receiving a stale 304. Errors and health/non-public responses are `no-store`.
- Added detail-free liveness/readiness probes. Readiness performs a database round trip but reports
  only `ok` or `unavailable` without exposing connection, schema, or exception information.
- Added a production public-server command, non-root/capability-free/read-only container baseline,
  loopback-bound Compose service, container health check, strict build context exclusions, and CI
  image build validation.
- Added a fixture-safe release smoke command and deployment runbook covering public/private network
  separation, least-privilege table grants, proxy/TLS requirements, release gates, cache/request
  controls, coordinated PostgreSQL/raw-storage backup, isolated restore rehearsal, and rollback.
- Added six public-release test functions plus two production configuration cases. Tests cover route
  isolation, security headers, trusted hosts, HSTS, ETag revalidation across a changed current Master,
  request/rate bounds, safe readiness failure, container constraints, and CI build enforcement.

### Validation performed

- Complete local suite: 293 passed in 42.88 seconds. Only upstream FastAPI/Starlette and the
  pre-existing inaccessible local pytest-cache warnings were emitted.
- Ruff passed for the entire repository and `git diff --check` passed.
- The configured PostgreSQL reported `20260912_0011 (head)` and Alembic reported no drift. T-019
  adds no migration. A separate empty validation database applied the complete T-001 through T-016
  migration chain to `0011`, passed current/drift checks, and was removed afterward.
- Docker built `assam-job-intelligence-public:t019` successfully. The image ran as non-root
  `appuser`, reached healthy status through `/readyz`, and passed the release smoke command against
  PostgreSQL.
- Live local public-runtime smoke checks returned 200 for health, readiness, `/jobs`, and the public
  API while `/review`, `/operations`, internal health, Swagger docs, and OpenAPI returned 404.
  CSP and ETag response headers were observed directly.

### Known limitations

- The V0 application limiter is per process; deployment must also enforce distributed request and
  connection bounds at its reverse proxy or edge.
- T-019 provides a hardened deployable baseline and runbook, not a selected hosted environment,
  managed DNS/TLS, registry promotion pipeline, or externally executed restore rehearsal. Those are
  T-020 release-operations concerns.
- The private application remains unauthenticated and must remain isolated. Only `app.public_main`
  is suitable for public routing.
- The public site remains empty until Human Review and the Master Publisher create an ACTIVE
  RecruitmentMaster; no real queued ReviewCase was approved for validation.
