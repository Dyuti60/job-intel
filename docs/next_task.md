# Next task: Assam source expansion — custom recruitment portals

Implement only the next portal/API batch from the authoritative source registry:

- `AMTRON_ASSAM`
- `AAU_ASSAM`

Create the smallest bounded `CUSTOM_PORTAL_API` family that can establish stable official
advertisement identity and resolve an authority-owned recruitment document before Candidate
creation. Preserve `AJI_HISTORY_LOOKBACK_MONTHS`, lifecycle exclusion, deterministic identity,
same-authority safety, idempotency, and shared Advertisement-to-Post structuring.

Application forms or login portals alone are not advertisements. Register a source only after
deterministic fixtures and one bounded non-persistent official live validation reach a usable
recruitment document. Do not implement the later special-case batch in this task.
