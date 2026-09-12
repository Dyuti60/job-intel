# T-004 — Recruitment Candidates and Extracted Fields

## Objective

Establish the persistent candidate and field-level extraction model that transforms immutable source
document versions into structured, traceable recruitment proposals without treating them as
verified or approved master data.

## Scope

T-004 will introduce `RecruitmentCandidate`, candidate revision and status metadata, and
`CandidateField`. Candidate fields will retain typed or structured extracted values together with
field-level provenance linking each value to the exact `SourceDocument` version from which it was
derived. The design will establish a deterministic candidate identity and deduplication baseline so
repeated processing does not create uncontrolled duplicate candidates while changed source
documents can produce auditable candidate revisions.

T-004 will add the required Alembic migration, constrained states, relationships, repositories,
services, operational APIs, and automated tests. Candidate data remains raw/discovery-side proposed
data and must not write directly to Recruitment Master.

## Boundaries

T-004 will not implement live crawling, HTML/PDF parsing, automated extraction, LLM integration,
Verification, confidence scoring, conflict detection, Human Review, approval, publishing,
Recruitment Master, public job search, or user-facing features. Tests will submit controlled
candidate and extracted-field inputs tied to existing source-document fixtures.
