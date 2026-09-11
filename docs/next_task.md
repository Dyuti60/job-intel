# T-003 — Source Documents and Discovery Runs

## Objective

Establish the persistent execution and raw-document provenance infrastructure required for future
registered-source discovery.

## Scope

T-003 will introduce `DiscoveryRun` and `SourceDocument` domain models and a new Alembic
migration. A discovery run will identify the registered source endpoint being processed and retain
execution status, start/completion timestamps, outcome metadata, and actionable failure details.
Source documents will retain source-to-run relationships, original URL and retrieval metadata,
deterministic document identity and content-hash metadata, media/content metadata, timestamps, and
raw-document provenance sufficient to explain what was observed and when.

The repository, service, schema, and API or internal execution interfaces needed to create and
inspect these records must remain explicit and testable. Idempotency and uniqueness rules must
prevent the same fetched representation from producing uncontrolled duplicate document records
while preserving repeat-run history.

## Boundaries

T-003 will not implement live crawling, scheduled workers, arbitrary internet discovery, HTML or PDF
parsing, recruitment extraction, `RecruitmentCandidate`, candidate fields, Evidence, Verification,
confidence scoring, Human Review, approval, publishing, or Recruitment Master. Tests will use local
fixtures or constructed metadata and must not depend on live Assam websites.
