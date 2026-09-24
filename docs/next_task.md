# Next task: Assam source expansion — special-case official sources

Implement only the next special-case batch from the authoritative source registry:

- `GHC_ASSAM`
- `SLRC_ASSAM`

Implement the narrow authority-specific discovery rules that cannot safely fit the reusable
families: Assam/Principal Seat ownership for Gauhati High Court, and stable campaign identity for
State Level Recruitment Commissions. Preserve `AJI_HISTORY_LOOKBACK_MONTHS`, lifecycle exclusion,
deterministic identity, same-authority safety, idempotency, and shared Post structuring.

Register a source only after deterministic fixtures and one bounded non-persistent official live
validation reach a usable, authority-owned recruitment advertisement. Do not implement the
discovered-only sources in this task.
