# Next task: Assam source expansion — AYUSH and Soil activation

Implement only the next evidence-backed existing-family batch:

- `AYUSH_ASSAM`
- `SOIL_ASSAM`

Extend `CMS_DETAIL` for AYUSH's paginated recruitment index and node details, including strict
lifecycle exclusion. Extend `OFFICIAL_ARCHIVE` for Soil Conservation's stable recruitment portlet,
deriving safe classification metadata without downloading or accepting unlabeled documents
blindly.

Use deterministic fixtures and one bounded non-persistent live validation per source. Register only
after an authority-owned recruitment advertisement resolves safely. Do not implement ASU or Home &
Political in this batch.
