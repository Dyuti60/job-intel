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

## Staged activation attempt — 24 September 2026

The required `workers.scheduler --due --dry-run` preflight could not connect to the configured local
PostgreSQL service at `localhost:5433`. No PostgreSQL service, Docker daemon, or alternate local
container engine was available. The command was stopped after one connection attempt; it performed
no network discovery and no persistence. Because the due set could not be established, the normal
persistent scheduler was not executed.

| Source | Run status | READY / DEGRADED / BLOCKED | Review / Master outcome | Note |
|---|---|---|---|---|
| `APSC` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `SLPRB_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `DEE_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `DHS_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `DME_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `DTE_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `ASDMA_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `FREMAA_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `APGCL_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `AEGCL_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |
| `SOIL_ASSAM` | NOT RUN | NOT CLASSIFIED | No change | Scheduler preview blocked by unavailable database |

Activation result: **0 due sources executed; 0 newly classified READY, 0 DEGRADED, 0 source-level
BLOCKED**. The activation environment is **BLOCKED** until PostgreSQL is available. Existing bounded
readiness classifications above remain unchanged; there is no evidence of a source or adapter defect.

## Persistent staged activation — 29 September 2026

The later persistent due-source run completed for all 11 enabled sources. This table reconciles the
latest immutable PipelineRuns and their Verification, Review, and Master Publisher outcomes; no
source was rerun for reconciliation.

| Source | Pipeline | Classification | Review / Master reason | Action |
|---|---|---|---|---|
| `APSC` | SUCCESS | READY | Reused 1 revision; Verification and Publisher succeeded; backlog remained review-pending | Normal cadence |
| `SLPRB_ASSAM` | PARTIAL | READY | 3 uncertain Post-age ownership warnings were preserved; 10 existing active reviews; Publisher failed 0 | Review ambiguous facts normally |
| `DEE_ASSAM` | SUCCESS | READY | 2 revisions verified and 2 ReviewCases queued; Publisher failed 0 | Review queued records |
| `DHS_ASSAM` | PARTIAL | DEGRADED | 14 revisions verified and queued; all LEGACY_UNSPLIT; 5 documents yielded no supported facts | Monitor extraction quality and enrich in Review |
| `DME_ASSAM` | PARTIAL | DEGRADED | 24 revisions verified and queued; all LEGACY_UNSPLIT; 10 documents yielded no supported facts | Monitor extraction quality and enrich in Review |
| `DTE_ASSAM` | SUCCESS | READY | No qualifying Candidate revision in this run; all stages succeeded | Normal cadence |
| `ASDMA_ASSAM` | SUCCESS | READY | Reused 10 revisions; all stages succeeded | Normal cadence |
| `FREMAA_ASSAM` | PARTIAL | READY | Bounded 20-document limit reached; 12 revisions verified and queued; Publisher failed 0 | Review queued records; retain bound |
| `APGCL_ASSAM` | PARTIAL | READY | 1 out-of-window document safely excluded; 2 revisions verified and queued; Publisher failed 0 | Review queued records |
| `AEGCL_ASSAM` | PARTIAL | READY | 2 out-of-window documents safely excluded; 9 revisions verified and queued; Publisher failed 0 | Review queued records |
| `SOIL_ASSAM` | SUCCESS | READY | 1 revision verified and queued; Publisher failed 0 | Review queued record |

Result: **5 SUCCESS, 6 PARTIAL, 0 FAILED; 9 READY, 2 DEGRADED, 0 BLOCKED**. There
is **no release blocker**. Every new ReviewCase inspected was queued against a verified immutable
revision, and publisher skips were `REVIEW_PENDING`; no run revision produced a premature publication
event. Candidate keys were unique within every reconciled source, with no duplicate current job
created. Operations records the common attempt time, latest PipelineRun status, full-success time,
next due time, group, and priority for all 11 sources. A PARTIAL run does not overwrite the distinct
last fully successful timestamp.

The Publisher safely rescanned an increasing review backlog (up to 92 assessments by the SOIL run).
It caused no correctness failure and is recorded only as a follow-up performance optimization.

## DHS/DME extraction hardening â€” 29 September 2026

The shared official-archive Post structurer now recognizes explicit single-Post titles, bounded
whitespace vacancy tables, and numbered position/count rows. It still rejects incomplete tables as
`AMBIGUOUS` and retains unsupported content as `LEGACY_UNSPLIT`; no persisted history was rewritten.

| Source | Persisted representative comparison | Bounded live check | Classification / remaining action |
|---|---|---|---|
| `DHS_ASSAM` | 4 documents: before 0 Posts / 0 AMBIGUOUS / 4 LEGACY; after 3 Posts / 1 AMBIGUOUS / 1 LEGACY | Reachable; one document resolved; sampled image/unsupported PDF remained LEGACY_UNSPLIT | DEGRADED â€” evaluate bounded scanned-PDF text recovery; keep Review fallback |
| `DME_ASSAM` | 4 documents: before 0 Posts / 0 AMBIGUOUS / 4 LEGACY; after 4 Posts / 0 AMBIGUOUS / 2 LEGACY | Reachable; one document resolved; sampled image/unsupported PDF remained LEGACY_UNSPLIT | DEGRADED â€” evaluate bounded scanned-PDF text recovery; keep Review fallback |

Both checks were non-persistent, fetched at most one qualifying document, and fabricated no Posts.
