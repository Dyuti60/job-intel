# T-021 — Deterministic Eligibility Rules and Matching Baseline

T-021 should introduce an explainable Assam recruitment eligibility domain over approved current
RecruitmentMaster data without changing Master history.

It should include:

- versioned deterministic eligibility-rule definitions for age, qualification, domicile,
  experience, category relaxation, and other explicitly supported approved fields
- typed applicant-input schemas without persistent user profiles
- field-level eligibility outcomes with exact MasterField and rule-version provenance
- UNKNOWN / REVIEW_REQUIRED behavior for missing, ambiguous, or unsupported requirements
- deterministic candidate-level aggregation that never turns absent evidence into eligibility
- a read-only eligibility-evaluation API and comprehensive fixture-based tests
- strict separation from Discovery, Verification, Human Review, Master publishing, and public
  deployment operations

T-021 must NOT implement user accounts, saved profiles, alerts, preparation features, payments,
LLM decisions, live crawling, or automatic Human Review.

Do not implement T-021 now.
