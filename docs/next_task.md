# T-009 — Local Human Review Web Interface

## Objective

Implement a locally hosted server-rendered review interface consuming the T-008 domain,
services, and APIs.

## Scope

The interface should let a reviewer view the queue by priority, open a ReviewCase, inspect
candidate/recruitment identity, original CandidateField values, confidence scores and component
breakdowns, review reasons, extraction Evidence, Verification Evidence assessments, source URLs
and classes, submit approve-as-is/correct-and-approve/reject/request-reverification decisions,
enter a reviewer identifier and notes, and see case progress and final outcome.

Use FastAPI server-rendered HTML/templates or another minimal local approach. Do not add React or
Angular.

## Boundaries

T-009 must not implement Recruitment Master or Master publication.
