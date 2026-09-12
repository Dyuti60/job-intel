# T-005 — Candidate Evidence and Extraction Provenance

## Objective

Establish the explicit evidence layer that supports unverified CandidateFields with bounded,
integrity-protected source context before any Verification capability is introduced.

## Scope

T-005 will introduce Evidence records linked to CandidateFields and their exact immutable
`SourceDocument` versions. Evidence will retain a provider-neutral source locator, a bounded source
excerpt or raw context, an explicit evidence type, provenance describing how the evidence was
captured, and deterministic integrity/hash metadata where appropriate.

T-005 will define CandidateField-to-Evidence relationships, constraints preventing cross-document
provenance mismatches, idempotent evidence identity, repositories, services, internal APIs, a new
Alembic migration, and automated tests. The design must preserve multiple evidence records when
needed without treating evidence as a verified fact.

## Boundaries

T-005 will not implement Verification, confidence scoring, conflict resolution, Human Review,
approval, Recruitment Master, live source crawling, HTML/PDF parsing, OCR, LLM extraction, or
public/user-facing features. Evidence remains untrusted extraction provenance for later independent
Verification.
