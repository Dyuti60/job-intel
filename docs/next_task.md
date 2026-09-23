# Next task: Assam source expansion — power-sector HTML family

Implement only Batch 3 from the authoritative source registry:

- `APDCL_ASSAM`
- `APGCL_ASSAM`
- `AEGCL_ASSAM`

Create one bounded `CUSTOM_HTML_LISTING` family for the three official power-sector career
surfaces. Use shared lifecycle classification, reliable-date handling through
`AJI_HISTORY_LOOKBACK_MONTHS`, deterministic Candidate identity, same-authority document safety,
idempotency, and the existing Advertisement-to-Post pipeline. Keep selectors and domain aliases in
source configuration rather than creating unrelated adapters.

Register a source only after deterministic fixtures and one bounded non-persistent official live
validation reach a usable recruitment document. Do not implement later registry batches in this
task.
