# T-008 — Human Review Queue and Decision Workflow

## Objective

Introduce the persistent Human Review domain driven by T-007 routing metadata.

## Scope

T-008 should introduce `ReviewItem`, field/revision review scope as appropriate, a
queued/reviewing/resolved lifecycle, priority, review-reason snapshot, confidence snapshot,
verification provenance snapshot/reference, reviewer decision, corrected value where permitted,
decision note, approve/correct/reject/reverify outcomes, and complete audit history.

## Boundaries

T-008 must not implement the browser/local Human Review UI. The local review page will be a later
task consuming the T-008 APIs.
