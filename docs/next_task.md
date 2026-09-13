# V1-M5 — Public Post product and deterministic eligibility

Make each approved Master Post an independently discoverable public job while retaining its parent
Advertisement context, then evaluate applicants only against approved Post-level facts.

The milestone should include:

- Post-first public list/detail API and `/jobs` pages sourced only from ACTIVE current Master data
- stable Post identity, parent Advertisement context, approved structured facts, and official links
- useful deterministic Post filters without exposing Candidate, Evidence, Confidence, Review, or
  private audit data
- a versioned deterministic eligibility rule/evaluation model tied to the exact Master revision and
  Master Post
- field-level `ELIGIBLE`, `NOT_ELIGIBLE`, `UNKNOWN`, and `REVIEW_REQUIRED` outcomes with explanations
- conservative handling of absent, ambiguous, or unsupported requirements
- migration, API, UI, security-boundary, idempotency, integrity, and rollback coverage

Do not infer missing requirements as eligible. Do not add user accounts, preparation features, or
LLM-dependent logic.
