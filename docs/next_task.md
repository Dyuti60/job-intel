# T-006 — Verification Runs and Field Verification

## Objective

Establish the independent Verification domain that evaluates a fixed RecruitmentCandidateRevision
and produces explainable, field-level results without mutating candidate extraction history.

## Scope

T-006 will introduce `VerificationRun` and `FieldVerification`, verification statuses and outcomes,
the exact CandidateRevision snapshot being verified, explicit relationships to Evidence evaluated
during verification, source-authority-aware deterministic verification inputs, recorded reasons and
findings, a conflict-detection baseline, repositories, services, internal APIs, a new Alembic
migration, and comprehensive automated tests.

The verification result for each field must remain explainable from immutable candidate values,
evidence, source metadata, and deterministic findings. Verification must remain independent of
Discovery and must not silently alter RecruitmentCandidateRevision, CandidateField, Evidence, or
approved/master data.

## Boundaries

T-006 will not implement final confidence-scoring policy beyond minimal deterministic inputs needed
for verification, Human Review UI, approval, Recruitment Master, publication, or live source
crawling.
