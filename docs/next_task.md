# Next task: Assam source production readiness

Validate the enabled Assam source set as a production operating unit:

- registry and scheduler configuration consistency
- one bounded non-persistent smoke check per enabled source
- source-specific operational blockers and runbook readiness

Do not expand source coverage or reactivate withheld sources. Confirm that enabled sources retain
bounded request behavior, rolling history policy, lifecycle exclusion, deterministic identity, and
safe Advertisement-to-Post routing under current official surfaces.

Document operational readiness and exact blockers only. Do not run historical backfills or write
to production data during validation.
