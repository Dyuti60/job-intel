# V1-M2 — Deterministic multi-post extraction

Implement deterministic extraction that can populate the Advertisement/Post foundation from
official vacancy tables and clearly bounded post-wise sections.

The milestone should include:

- a reusable extraction result with separate advertisement facts and post facts
- explicit vacancy-table and post-section parsing with stable post keys
- shared advertisement facts such as application dates without copying their provenance
- post-specific vacancy, qualification, age, pay, reservation, and other supported facts
- `AMBIGUOUS` output with source locators when row/column or post ownership cannot be decided safely
- deterministic fixtures covering a multi-post SLPRB-style advertisement and ambiguous layouts
- Evidence attached to every emitted CandidateField and no live-site dependency in CI

Do not publish Posts to Master or implement Confidence V2 in this milestone. Those changes follow
after extraction shape and provenance are proven.
