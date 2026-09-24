# Assam enabled-source production readiness

Validated 24 September 2026 with one bounded, non-persistent smoke check per source. The authoritative
inventory, runtime registry, and scheduler contain the same 11 enabled source codes. Group, priority,
cadence, and adapter mappings are consistent; there are no duplicate, missing, or extra enabled
registrations.

| Source | Adapter family | Group / priority | Smoke | Readiness | Warning / production action |
|---|---|---:|---|---|---|
| `APSC` | `CUSTOM_PORTAL_API` | HIGH_PRIORITY / 10 | Advertisement resolved; EXPLICIT, 1 Post | READY | None |
| `SLPRB_ASSAM` | `OFFICIAL_ARCHIVE` | HIGH_PRIORITY / 20 | Document resolved; EXPLICIT, 2 Posts | READY | Bounded validation processed 1 of 10 listing items |
| `DEE_ASSAM` | `OFFICIAL_ARCHIVE` | HIGH_PRIORITY / 30 | Document resolved; LEGACY_UNSPLIT | READY | Human Review fallback remains required for the sampled document |
| `DHS_ASSAM` | `OFFICIAL_ARCHIVE` | HIGH_PRIORITY / 35 | Document resolved; LEGACY_UNSPLIT | READY | Sample yielded no supported facts beyond safe metadata; monitor Review enrichment |
| `DME_ASSAM` | `OFFICIAL_ARCHIVE` | NORMAL / 40 | Official document resolved through bounded pipeline | READY | Retain Human Review fallback when structure is unsupported |
| `DTE_ASSAM` | `DATED_DOCUMENT_RESOLVER` | HIGH_PRIORITY / 42 | Official document resolved through bounded pipeline | READY | Retain bounded dated-document traversal |
| `ASDMA_ASSAM` | `OFFICIAL_ARCHIVE` | NORMAL / 60 | Document resolved; LEGACY_UNSPLIT | READY | Bounded validation processed 1 of 10 advertisements |
| `FREMAA_ASSAM` | `DATED_DOCUMENT_RESOLVER` | NORMAL / 64 | Document resolved; LEGACY_UNSPLIT | READY | Bounded validation processed 1 of 29 rows |
| `APGCL_ASSAM` | `CUSTOM_HTML_LISTING` | NORMAL / 67 | Document resolved; LEGACY_UNSPLIT | READY | Bounded validation processed 1 of 4 rows |
| `AEGCL_ASSAM` | `CUSTOM_HTML_LISTING` | NORMAL / 68 | Document resolved; LEGACY_UNSPLIT | READY | Bounded validation processed 1 of 11 rows |
| `SOIL_ASSAM` | `OFFICIAL_ARCHIVE` | NORMAL / 84 | Document resolved; LEGACY_UNSPLIT | READY | Safe labeled-listing context retained |

## Summary

- Enabled: **11**; READY: **11**; DEGRADED: **0**; BLOCKED: **0**.
- Release blockers: **none found in this bounded validation**.
- All adapters retain the configured rolling history cutoff, request bounds, lifecycle exclusion,
  deterministic identity, same-authority safety, bounded raw excerpts, and shared
  Advertisement-to-Post routing. Unsupported structure remains `AMBIGUOUS`/`LEGACY_UNSPLIT` for
  Human Review; no source bypasses Verification, Review routing, or Master publication.
- Operations exposes persisted last attempt/success, pipeline status/failure, next due/cadence,
  group, and priority. Production should begin with a staged due-source execution and operator
  observation rather than a historical backfill.
