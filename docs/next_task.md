# Next task: Assam source expansion — bounded CMS detail activation

Implement only Batch 2 from the authoritative source registry:

- `AGRI_ASSAM`
- `NHM_ASSAM`
- `ASRLM_ASSAM`
- `SAMAGRA_ASSAM`

Extend the existing bounded `CMS_DETAIL` family with explicit source-owned listing aliases and
listing-to-detail-to-document rules. Preserve same-domain safety, `AJI_HISTORY_LOOKBACK_MONTHS`,
lifecycle exclusion, deterministic Candidate identity, idempotency, and shared
Advertisement-to-Post structuring.

Existing Agriculture and NHM candidate configurations are not activation evidence. Register a
source only after deterministic fixtures and one bounded non-persistent official live validation
reach a usable recruitment document. Do not implement later registry batches in this task.
