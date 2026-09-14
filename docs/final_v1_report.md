# Assam Job Intelligence V1 final report

Status date: 2026-09-14

## Outcome

V1 is implemented as a deterministic, Assam-only recruitment intelligence pipeline. It keeps raw
official evidence, discovery candidates, verification assessments, Human Review decisions,
immutable approved Master history, the public Post projection, and stateless eligibility as
separate concerns. No external AI provider is required by the runtime.

The software and local operating path are release-ready. Public production activation is not yet
complete: the GitHub repository has no `public-production` environment, and its protected database,
hostname, base-URL, DNS, and backup configuration have not been supplied. The project therefore
does not claim a deployment that did not occur.

## Implemented system

The implemented trust chain is:

1. registered official Assam recruiting-authority endpoint;
2. bounded retrieval and content-addressed raw storage;
3. idempotent discovery observation and Candidate revision;
4. explicit Advertisement and Post interpretation;
5. evidence-linked deterministic verification and Confidence Policy V1/V2;
6. separate explainable Review Routing Policy V1 and private Human Review;
7. fail-closed Publisher projection into immutable Master revisions;
8. Post-first public HTML/JSON search and detail pages; and
9. stateless, deterministic eligibility against one exact approved Master Post revision.

Discovery cannot write Master data. Verification cannot approve data. Human decisions and
corrections are audited. Publishing validates the assessment, routing, review, and provenance
snapshots again before mutation. Previously approved values remain available through immutable
Master revisions and change history.

## Official-source coverage

Five sources are enabled:

| Code | Adapter family | Schedule |
| --- | --- | --- |
| APSC | custom official recruitment portal | high priority, every 6 hours |
| SLPRB_ASSAM | authority-specific table and PDF adapter | high priority, every 6 hours |
| DEE_ASSAM | reusable official document-list CMS adapter | high priority, every 12 hours |
| DME_ASSAM | reusable official document-list CMS adapter | normal, every 24 hours |
| ASDMA_ASSAM | reusable structured-resource table extension | normal, every 24 hours |

The historical policy is the current Asia/Kolkata calendar year and the two prior calendar years,
currently 2024-2026. Lifecycle material such as results, merit/selection lists, interviews,
verification, admit cards, appointments, answer keys, cancellations, postponements, extensions,
corrigenda, and addenda is retained as source evidence when encountered but is not promoted as a
new job.

The local PostgreSQL evidence set after the bounded ASDMA backfill contains:

| Authority | Candidates | Candidate revisions | Source documents |
| --- | ---: | ---: | ---: |
| APSC | 1 | 1 | 3 |
| ASDMA_ASSAM | 40 | 40 | 42 |
| DEE_ASSAM | 6 | 6 | 8 |
| DME_ASSAM | 1 | 1 | 4 |
| SLPRB_ASSAM | 10 | 10 | 12 |
| **Total** | **58** | **58** | **69** |

ASDMA contributed 19 dated 2024 advertisements, 16 dated 2025 advertisements, and 5 dated 2026
advertisements. Its source run discovered 42 documents and created 40 Candidates; the archive
listing itself and one cancellation notice correctly created no Candidate. A lifecycle-term audit
found no lifecycle notice in Candidate titles. The raw store contains the same 69 source files
(62,859,103 bytes), partitioned by source.

The ASDMA pipeline run `59ca7661-3937-4498-8d69-835dca25aa86` completed `PARTIAL`, with no source
failure: 40 Master records were created and one case was routed for Human Review. `PARTIAL` is the
intended result when unresolved review work remains. A prior operator-interrupted exploratory run
is retained as a failed PipelineRun with the explicit
`OPERATOR_INTERRUPTED_CLASSIFIER_FIX` code; no domain records were written by that run.

These figures describe actual local evidence, not theoretical archive coverage. Enabled adapters
remain conservative and legacy documents remain `LEGACY_UNSPLIT` unless an explicit supported Post
structure exists. No Post is invented from ambiguous prose.

The evidence-backed backlog includes NHM Assam, Samagra Shiksha Axom, ASRLM/P&RD, Agriculture,
FREMAA, P&RD documents, Niyukti, and later district/university/board/court/power sources. They stay
disabled until stable official traversal and lifecycle classification are fixture-proven.

## Scheduling and private operations

The source registry owns schedule group, interval, priority, per-minute request bound, and last
attempt/success state. `workers.scheduler` supports one source, one group, due sources, or every
enabled source. Selection is stable by priority then code; each source has an independent lock,
PipelineRun, schedule update, and failure result, so one failure does not stop other selected
sources. The GitHub workflow runs due sources daily at 08:00 Asia/Kolkata and evaluates monitoring
for all registered sources.

The private `/operations` page exposes the same bounded choices plus Publisher and monitoring.
Mutations require a same-origin URL-encoded form. The server accepts only enums and registered
source/group values and calls shared application services; it never accepts or invokes a shell
command. The public application does not mount this route. Dry-run is the UI default.

## Public product and eligibility

Approved explicit Posts are independently addressable public jobs with stable UUIDv5 identities,
parent Advertisement context, exact selected-Post facts, and official-source provenance. Historical
unsplit records remain compatibility results. Public filters are bounded and the public process
does not mount discovery, review, operations, audit, or administration routes.

Eligibility Policy V1 evaluates age, Assam domicile, exact qualification text, and structured
experience against an exact approved Master revision. Outcomes and criterion reasons are
deterministic: `ELIGIBLE`, `NOT_ELIGIBLE`, `UNKNOWN`, or `REVIEW_REQUIRED`. Applicant inputs and
results are not persisted, and responses are not cached. Free-text equivalence and absent or
prose-only relaxation rules intentionally do not produce guesses.

## Verification evidence

- Database migration head: `20260914_0016`; populated upgrade, downgrade/re-upgrade, schema-drift
  checks, and a fresh full migration chain were completed during the milestones.
- M6 exact commit `ca57d58212fb5a1c40be21c6658bfb1a79d8a9ef` passed GitHub CI run
  `34809437968`.
- M7 application commit `a857fc6b1a639572676ec8ff671a81b92f562034` passed GitHub CI run
  `34811090018` after 338 local tests, lint, migration-drift checks, and a successful hardened
  public Docker build.
- Non-deploying Public Release run `34811277289` built and scanned the same M7 SHA, pushed its
  immutable image, and published provenance successfully. No production deployment was requested.
- Trusted Assam Pipeline run `34811450838`, attempt 2, successfully upgraded the persistent
  database, reported migration head, ran a bounded DEE dry-run, and evaluated all-source
  monitoring. Attempt 1 accurately failed at database connection because the project container was
  not published on its configured `localhost:5433` endpoint; the endpoint was restored with its
  named data volume preserved before the successful rerun.
- Live 2026-09-14 validation reached the DEE, DME, and ASDMA official pages with HTTP 200. APSC and
  SLPRB returned gateway 502 during that validation and were recorded as unavailable rather than
  successful.
- The registered Windows X64 self-hosted runner was online and Docker Engine 29.7.2 was available
  during final readiness checks.

## Production activation boundary

The Public Release workflow builds an immutable SHA-tagged public image, scans it, pushes it to
GHCR, and publishes provenance before an optional protected deployment. Deployment additionally
requires the `public-production` environment, protected database and backup secrets, public
hostname/base-URL variables, DNS/TLS ingress, and an approved release decision. At report time the
environment did not exist, the availability job was skipped, and Restore Rehearsal had not run. The
non-deploying Public Release artifact gate did pass. Production activation and recovery rehearsal
remain operator-owned prerequisites, not facts the code can fabricate.

## Explicit V2 deferrals

- assisted source-candidate proposal, never autonomous source enablement;
- qualification ontology/equivalence and richer category-relaxation interpretation;
- deterministic Post extraction for additional source-specific document layouts;
- deliberate conversion of reviewed legacy-unsplit advertisements into explicit Posts;
- production identity/SSO and authorization policy for private web surfaces;
- production observability integration, DNS/TLS ingress, protected environment configuration, and
  scheduled restore-rehearsal operations.
