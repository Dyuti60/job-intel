# Intended recruitment lifecycle

T-001 documents but does not implement these future domain states.

```text
DISCOVERED
  -> EXTRACTED
  -> PENDING_VERIFICATION
  -> VERIFIED
  -> APPROVED
  -> PUBLISHED
```

Verification can route a candidate to `REVIEW_REQUIRED`; successful human resolution can then lead
to `APPROVED`. `EXTRACTION_FAILED` and `VERIFICATION_FAILED` retain actionable failure context.
`REJECTED` records an explicit decision not to publish. `STALE` identifies a candidate or source
observation no longer suitable for publication. Future transition rules must be explicit, tested,
audited, and safe to retry.

Discovery stores source documents, candidates, evidence, and run history in the raw/discovery side.
Verification assesses individual claims without mutating authoritative master records. Important
fields retain their supporting evidence and provenance. Human Review is required when deterministic
policy identifies conflicts, missing or stale evidence, low confidence, or critical risk. Only an
explicit approval makes a revision eligible for idempotent publication.

## Change workflow

```text
Existing recruitment
  -> source/document change detected
  -> candidate revision
  -> verification
  -> review where required
  -> approval
  -> master update
  -> change history retained
```

A changed source produces a new candidate revision rather than directly editing the master. The
publisher compares an approved revision with current master data, writes only a valid change, and
records old and new values plus approval and evidence references. Retrying discovery or publication
must not create duplicate master records or duplicate effective changes.

## Registered-source gate

Future Discovery starts by enumerating the Source Registry, not the open internet. An endpoint is
eligible for scheduled enumeration only when it belongs to an active recruiting authority, its
endpoint status is active, and `discovery_enabled` is true. Inactive or disabled records remain in
the registry for operational history and provenance but are skipped.

Source class informs future verification: authoritative official sources can establish truth,
official supporting sources can corroborate it, and secondary/discovery-only sources can assist
discovery or cross-checking but cannot silently override authoritative evidence. T-002 only records
this metadata; it performs no fetching, evidence creation, or confidence calculation.

## Discovery execution and document change workflow

```text
eligible SourceEndpoint
  -> RUNNING DiscoveryRun
  -> controlled document observation
  -> normalize URL + calculate/validate SHA-256
  -> NEW / UNCHANGED / CHANGED
  -> immutable SourceDocument version + run observation
  -> SUCCEEDED / PARTIAL / FAILED run
```

Only an active endpoint owned by an active authority with `discovery_enabled=true` may start a new
run. A run begins in RUNNING state and may complete once as SUCCEEDED, PARTIAL, or FAILED.
Completion records `completed_at`; partial and failed executions may retain an error code and
message. Completed runs reject new observations.

The first normalized URL/hash observed for an endpoint is NEW. A known normalized URL/hash is
UNCHANGED and reuses the existing version while updating `last_seen_at` and the latest run
reference. A known normalized URL with a previously unseen hash is CHANGED and creates a new
version. CHANGED never overwrites an old content hash or document record. Different URLs are not
merged solely because they have identical bytes.

Every accepted observation creates—or idempotently reuses within the same run—a run/document
association containing its classification and HTTP/content metadata. Run counters change only with
new association records, keeping retries within one run from inflating totals. No live network
fetching, parsing, extraction, candidate creation, or Evidence creation occurs in T-003.

## Candidate proposal and revision workflow

```text
ACTIVE SourceDocument
  -> logical RecruitmentCandidate (DRAFT)
  -> controlled structured proposal
  -> immutable RecruitmentCandidateRevision
  -> typed CandidateFields with exact document provenance
  -> READY_FOR_VERIFICATION
```

Candidate identity is authority plus normalized candidate key. Duplicate creation is rejected, and
a discarded candidate remains retained for audit and deduplication. Candidate creation requires an
active authority but does not require an active discovery endpoint.

A revision accepts controlled fields rather than fetching or parsing its document. The service
validates field types, unique paths, active document state, and authority consistency, then hashes a
canonical source-and-fields representation. Replaying identical normalized fields in any order
against the same source document returns the existing revision and fields. A changed structured
value or changed source-document version creates the next monotonically numbered revision. Earlier
revisions and fields have no mutation API and remain intact.

A DRAFT candidate may become READY_FOR_VERIFICATION only after it has a revision containing fields,
or it may become DISCARDED. These transitions are not reversible in T-004. Discarded candidates
cannot receive revisions.

**READY_FOR_VERIFICATION does not mean verified.** Candidate data remains untrusted raw/discovery
data and cannot enter Recruitment Master. Evidence, Verification, review, approval, and publication
remain later independent stages.

## Candidate evidence attachment workflow

### Post interpretation workflow

```text
candidate revision extraction
  -> advertisement-level CandidateFields
  -> deterministic post split is explicit?
       yes -> AdvertisementRevision EXPLICIT
              -> one or more RecruitmentPosts
              -> post-relative PostFacts mapped to namespaced CandidateFields
       ambiguous -> AdvertisementRevision AMBIGUOUS, no invented Posts
       historical/unsupported -> AdvertisementRevision LEGACY_UNSPLIT, no invented Posts
```

Post keys and ordinals are unique inside one advertisement revision. The revision hash includes
explicit post identity and fact membership, while legacy advertisement-only hashing remains
byte-compatible with pre-migration revisions. PostFacts reuse CandidateFields so Evidence and
Verification provenance is not copied or weakened.

```text
immutable SourceDocument
  -> immutable CandidateRevision
  -> typed CandidateField
  -> bounded extraction Evidence attachment
  -> READY_FOR_VERIFICATION
  -> future independent Verification
```

Evidence is recorded idempotently from a usable SourceDocument version, with a controlled evidence
type, uninterpreted locator, bounded excerpt, and optional bounded context. Canonical normalization
and SHA-256 identity reuse an equivalent Evidence record. Changed context, locator, type, or exact
SourceDocument version creates a different record rather than rewriting history.

A CandidateField may link to several Evidence records, and one Evidence record may support several
fields from the same candidate revision document. Composite database constraints and service checks
reject cross-document extraction-evidence links. Replaying a link reuses the association and does
not mutate the CandidateRevision, CandidateField value, or candidate status.

T-005 Evidence is extraction provenance: it records the exact captured context that led to an
unverified field proposal. Future Verification may evaluate this evidence and may introduce
additional evidence concepts for corroboration or conflict analysis. Attaching extraction Evidence
does not itself verify a field, establish authority, calculate confidence, or make a candidate ready
or publishable.

## Verification workflow

```text
READY_FOR_VERIFICATION CandidateRevision
  -> PENDING VerificationRun with revision-hash snapshot
  -> RUNNING
  -> per-field snapshot and evidence assessments
  -> deterministic field outcome and explainable finding
  -> COMPLETED when all fields are finalized
     or PARTIAL when only some are finalized
  -> future confidence policy and Human Review routing
```

Each assessment refers to an existing Evidence record and marks it SUPPORTS, CONTRADICTS, or
CONTEXT_ONLY for that specific field verification. Unlike extraction Evidence links, verification
assessments may cross SourceDocuments and registered endpoints. The service derives and snapshots
the SourceEndpoint class from persisted provenance; callers cannot promote secondary evidence to
official or authoritative status.

Finalization applies the documented V0 precedence: authoritative contradiction wins first;
otherwise authoritative support confirms the value; without authoritative support, combined
support and contradiction conflict; no, context-only, secondary-only, or otherwise inadequate
evidence remains insufficient. NOT_APPLICABLE requires an explicit request. Findings retain all
counts, so a weaker contradiction remains visible even when authoritative support determines the
outcome.

Verification does not modify extracted data. CandidateRevision and CandidateField snapshots prove
what was evaluated, while Evidence and extraction associations remain unchanged. Finalized field
results and terminal runs reject mutation. Re-verification creates a new VerificationRun and
preserves the earlier result. T-006 records deterministic inputs only; numeric confidence, review,
approval, and publication remain later stages.

## Confidence and review-routing workflow

New verification runs now retain two parallel interpretations:

```text
finalized Verification facts -> immutable Confidence V1 -> legacy Review/Master compatibility
                             -> immutable Confidence V2 -> Routing V1 semantic risk assessment
```

Confidence V2 never sets review flags. Routing V1 reads the immutable V2 fingerprint plus
verification and Advertisement/Post interpretation, persists field-specific and revision-specific
reasons, and does not use a numeric threshold. Missing optional facts do not route; ambiguity,
conflict, partial verification, and insufficient critical support do. V2 is intentionally blocked
from the existing advertisement-level publisher pending Post-aware Master support.

```text
FINALIZED FieldVerification
  -> V1 field confidence calculation
  -> deterministic field review routing
  -> COMPLETED/PARTIAL VerificationRun aggregation
  -> revision confidence and review-required metadata
  -> future Human Review
```

Field confidence is calculated only from finalized verification snapshots, assessments, Evidence,
and registered source provenance. Source bonuses and penalties count distinct SourceEndpoints, so
several excerpts from one site cannot manufacture independent agreement. The persisted breakdown
shows the outcome anchor, capped support and contradiction modifiers, completeness signals,
thresholds, criticality, final score, and review reasons.

Criticality is derived from the CandidateField path under policy V1. Conflicts, insufficient
evidence, threshold failures, and a critical field without authoritative support route the field to
review with deterministic priority. Clients cannot submit criticality, source class, score, or
review routing.

For a COMPLETED or PARTIAL run, the service calculates missing eligible field assessments and then
aggregates CRITICAL fields at weight 2 and STANDARD fields at weight 1. NOT_APPLICABLE fields do not
enter the average. Verification coverage multiplies the weighted average; a PARTIAL run always
requires review. Any field-level review condition also survives aggregation, preventing a high
average from masking one dangerous field.

Replaying V1 calculations returns the same immutable assessment. Changed policy requires a new
policy version; changed persisted inputs after scoring are treated as an integrity conflict.
Confidence calculation does not modify extracted or verified data. Confidence does not approve
data, and high confidence does not itself publish data.

## Human Review workflow

```text
review-required RevisionConfidenceAssessment
  -> idempotent ReviewCase queue generation
  -> QUEUED
  -> explicit start to IN_REVIEW
  -> FIELD/REVISION item decisions
  -> automatic RESOLVED case outcome
  -> approved projection preview
  -> future Master Publisher
```

Queue generation revalidates confidence integrity and snapshots the revision score, policy,
priority, reasons, and breakdown. It creates one FIELD item for each routed field and one
consolidated REVISION item only for PARTIAL_VERIFICATION and/or
REVISION_SCORE_BELOW_THRESHOLD. Replaying the same revision-confidence assessment returns the same
case and items.

Review decisions require an explicitly started case and a nonblank reviewer identifier.
APPROVE_AS_IS retains an original value. CORRECT_AND_APPROVE is field-only and stores a normalized,
same-typed value that must differ from the original. REJECT and REQUEST_REVERIFICATION record their
decision only; reverification is not started automatically. Corrections, rejection, and
reverification require notes.

The last item decision resolves the case with deterministic precedence:
REVERIFICATION_REQUESTED, then REJECTED, then APPROVED_WITH_CORRECTIONS, then APPROVED. Exact
decision replay is idempotent; a different decision conflicts. Resolved or cancelled history is
immutable.

The approved projection includes original values for unrouted and approve-as-is fields and
corrected decision values for corrected fields. Rejected or reverification-requested cases are
explicitly not master-eligible and return no effective publishable values. The projection is a read
preview only. Human correction never rewrites CandidateField history, and T-008 performs no Master
publication.

## Local Human Review interface workflow

```text
Review Queue
  -> open ReviewCase
  -> POST Start Review
  -> inspect candidate, confidence, extraction Evidence, and verification assessments
  -> POST one immutable decision per routed item
  -> automatic case resolution after the final item
  -> approved projection preview
  -> future Master Publisher
```

The default queue shows QUEUED and IN_REVIEW cases in CRITICAL, HIGH, NORMAL, NONE order, oldest
first within a priority. Status and priority filters are read-only presentation controls. A case
page composes candidate/revision identity, source links, stored confidence components and reasons,
field values, extraction provenance, verification support/conflict assessments, progress, and
existing decisions without querying from templates or recalculating domain results.

Starting, cancelling, and deciding are POST operations followed by redirects. Decision forms call
the existing T-008 service, including reviewer/note rules and typed correction validation. The UI
does not directly change CandidateField, CandidateRevision, Evidence, Verification, or Confidence
records. Human correction never rewrites CandidateField history.

When the final item resolves a case, the UI displays the persisted outcome and reads the existing
approved projection. Approved and corrected values are previews only. REJECTED and
REVERIFICATION_REQUESTED cases visibly remain ineligible for Master publication, and requesting
reverification does not start a VerificationRun.

## Master publication workflow

```text
COMPLETED verification + confidence not requiring review
  -> Publisher integrity checks
  -> original CandidateField projection
  -> RecruitmentMaster

confidence requiring review
  -> RESOLVED APPROVED/APPROVED_WITH_CORRECTIONS ReviewCase
  -> existing approved projection
  -> Publisher integrity checks
  -> RecruitmentMaster
```

The Publisher is invoked with one explicit RevisionConfidenceAssessment. It revalidates the
CandidateRevision hash, VerificationRun snapshot, finalized field snapshots, Confidence input
fingerprints, complete run coverage, and, when required, ReviewCase snapshots and approved
projection eligibility. Required Human Review cannot be bypassed. REJECTED,
REVERIFICATION_REQUESTED, CANCELLED, unresolved, partial, failed, or stale inputs do not publish.

The effective values are original CandidateField values for direct publication and unrouted or
approve-as-is reviewed fields. CORRECT_AND_APPROVE uses the T-008 projection's normalized corrected
value while retaining both CandidateField and ReviewDecision provenance. Publishing never mutates
Candidate, Evidence, Verification, Confidence, or Review history.

```text
new effective values
  -> new immutable RecruitmentMasterRevision
  -> immutable MasterFields
  -> ADDED/UPDATED/REMOVED MasterChanges
  -> current-revision pointer advances

unchanged effective values
  -> existing RecruitmentMasterRevision reused
  -> UNCHANGED MasterPublicationEvent
  -> RecruitmentMaster.last_verified_at refreshed
```

Every successful distinct publication input creates a publication event. Replaying the same
confidence assessment is idempotent, and matching business content from a newer source or candidate
revision creates audit provenance without inventing another master revision. Master values are the
trusted internal projection, but T-010 does not expose a public search experience.

## Master Publisher worker workflow

```text
unpublished RevisionConfidenceAssessments on COMPLETED VerificationRuns
  -> deterministic oldest-first bounded scan
  -> classify direct/review state
  -> skip non-publishable review states
  -> MasterPublisherService integrity and projection rules
  -> Recruitment Master or unchanged-publication audit
  -> per-run operational summary
```

Direct no-review assessments and resolved APPROVED or APPROVED_WITH_CORRECTIONS cases are passed to
the existing Publisher one at a time. Missing or pending review, cancellation, rejection, and
reverification requests are normal skips. One item's domain/integrity error is logged and counted,
then processing continues; a database/session failure terminates the worker with a nonzero exit.

Successfully published assessment IDs are excluded from later scans through their unique
MasterPublicationEvent. Therefore a second periodic run with no new confidence or review result is
a no-op. A distinct newer assessment may still produce the T-010 UNCHANGED reverification event
when effective content matches an existing MasterRevision.

`--dry-run` performs selection, review classification, Publisher integrity validation, projection
hashing, and create/update/unchanged prediction without committing Master state. Scheduling remains
outside T-010B; cron, Windows Task Scheduler, or another orchestrator may invoke the command later.

## APSC Advertisement 12/2026 discovery workflow

```text
official APSC portal + public WhatsNew feed + official advertisement PDF
  -> APSC Discovery worker
  -> DiscoveryRun + NEW / UNCHANGED / CHANGED observations
  -> immutable SourceDocuments + raw:// references
  -> APSC_ADVT_12_2026 Candidate
  -> immutable CandidateRevision
  -> typed CandidateFields
  -> exact-document extraction Evidence
  -> STOP
```

The worker fetches only the official resources required by this narrow adapter. PDF failure after
a usable portal entry yields PARTIAL and retains supported portal facts; gaps are never filled from
third-party pages. Text PDFs are parsed deterministically without OCR. `10/09/2026` is explicitly
DD/MM/YYYY and normalizes to `2026-09-10`.

Identical bytes produce UNCHANGED observations and reuse Candidate, revision, Evidence, and links.
Changed bytes create a SourceDocument version; changed extraction creates the next immutable
CandidateRevision. Dry-run fetches/classifies but rolls back database changes and skips raw writes.
Verification remains a separate later stage: discovery does not verify, score, review, or publish.

## Additional official archive workflow

For extractable table text, the archive family separates shared advertisement facts from post rows:

```text
validated vacancy table
  -> explicit Post per row + category facts
  -> uniquely matched post-detail rows add qualification / age / pay / experience
  -> namespaced CandidateFields + exact row/column Evidence

damaged vacancy row -> AMBIGUOUS advertisement revision, no Posts
uncertain detail ownership -> keep valid Posts, add evidence-backed ambiguity fact
```

The parser is bounded to 100 rows and supported headers. Unknown headers and absent optional cells
stay unknown. It does not infer zeros from blanks/dashes, does not use a language model, and does
not fetch anything beyond the registered adapter workflow.

```text
official SLPRB / DEE / DME recruitment archive
  -> select explicit advertisements dated 2024 onward (for the 2026 two-year lookback)
  -> fetch and persist selected official PDFs
  -> immutable SourceDocument versions + raw:// references
  -> authority-scoped stable Candidate identity
  -> conservative CandidateFields + exact-document Evidence
  -> independent Verification + Confidence
  -> QUEUED Human Review when required
  -> STOP until human approval and a later Master Publisher pass
```

Run one source at a time with `python -m workers.pipeline --source SLPRB_ASSAM`, `DEE_ASSAM`, or
`DME_ASSAM`. Past examinations are not filtered from storage merely because their application
window has closed. They also do not become public automatically: only Human Review-approved and
published ACTIVE Master records appear under `/jobs`. An image-only advertisement remains captured
with a PARTIAL warning rather than receiving guessed fields.

## Automated Verification worker workflow

```text
eligible CandidateRevision
  -> CandidateService readiness transition when DRAFT
  -> VerificationRun (AUTOMATED or RETRY)
  -> one FieldVerification per CandidateField
  -> persisted extraction Evidence interpreted conservatively
  -> SUPPORTS / CONTRADICTS / CONTEXT_ONLY assessments
  -> deterministic T-006 final outcomes
  -> COMPLETED VerificationRun
  -> T-007 field and revision Confidence
  -> T-008 QUEUED ReviewCase when review_required
  -> STOP
```

The worker performs no network request and does not infer support merely because Evidence is
linked. Missing or ambiguous evidence is a valid insufficient result rather than a batch failure.
No-review results remain ready for the Master Publisher. Review-required results remain visible at
`/review` until a human acts; the worker neither starts cases nor submits decisions. Re-running
without a changed CandidateRevision or a newer reverification request is a no-op. Dry-run predicts
the complete route while rolling back Candidate readiness, Verification, Confidence, and Review
records.

## End-to-end pipeline workflow

```text
one-shot Pipeline execution
  -> source mapping (APSC / SLPRB_ASSAM / DEE_ASSAM / DME_ASSAM -> authority)
  -> existing source-specific Discovery worker
  -> existing Verification worker
  -> Confidence and Review routing inside Verification worker
  -> existing Master Publisher worker (always invoked after safe Verification)
  -> combined structured operational summary
```

Human Review remains asynchronous:

```text
pipeline run 1
  -> ReviewCase QUEUED
  -> Publisher skips pending review
  -> SUCCESS, Human Review Required

human resolves case through /review

pipeline run 2
  -> Discovery may be UNCHANGED
  -> Verification may scan zero revisions
  -> Publisher finds the resolved confidence/review state
  -> approved or corrected Master publication
```

The orchestrator never starts or decides a ReviewCase. Rejection stays unpublished, and a
reverification request is handled only by the existing one-shot T-012 retry rule. A fatal Discovery
failure prevents later stages. PARTIAL Discovery with usable official data continues. Dry-run calls
the established dry-run path of every stage and leaves all recruitment-domain persistence unchanged;
T-014 records only its operational run audit.

## Pipeline operational-history workflow

```text
pipeline CLI invocation
  -> PipelineRun RUNNING (operational audit commit)
  -> existing PipelineOrchestrator
       -> DISCOVERY          -> PipelineStageRun
       -> VERIFICATION       -> PipelineStageRun
       -> MASTER_PUBLISHER   -> PipelineStageRun
  -> structured combined summary
  -> PipelineRun SUCCESS / PARTIAL / FAILED with completion timing
```

Every invocation creates separate operational history, including idempotent runs that produce no
new domain records. Failure metadata is bounded and excludes stack traces. Dry-run also creates this
audit, but source/candidate/verification/review/master mutations remain rolled back. `RUNNING`
records are groundwork for T-015 overlap protection; no lock or scheduler exists yet.

## GitHub CI workflow

```text
developer feature branch
  -> push
  -> pull request targeting main
  -> GitHub-hosted Ubuntu CI
       -> Python 3.12 + frozen uv environment
       -> temporary PostgreSQL readiness
       -> Alembic upgrade / current / check
       -> full fixture-only Pytest suite
       -> Ruff
  -> merge main after required checks pass
```

Pushes to `main` and manual workflow dispatch run the same checks. CI uses temporary workflow
credentials and never executes the live APSC pipeline. Persistent self-hosted execution is T-015.

## Scheduled trusted pipeline workflow

```text
workflow_dispatch                         daily 02:30 UTC / 08:00 IST
        \                                      /
         -> GitHub Actions APSC concurrency <-
              -> trusted Windows x64 self-hosted runner
              -> resolve external runtime configuration
              -> validate external raw-storage root
              -> Alembic upgrade/current
              -> acquire source-scoped PostgreSQL advisory lock
              -> existing T-013 PipelineOrchestrator
                   -> Discovery
                   -> Verification + Confidence + Review routing
                   -> Master Publisher
              -> PipelineRun/StageRun history
              -> GitHub Actions operational summary
```

Manual runs use trigger `GITHUB_ACTION`; scheduled runs use `SCHEDULED`. GitHub concurrency prevents
two workflow jobs from running together, and the database advisory lock prevents overlap with any
local CLI process using the same source. Lock contention fails without starting domain work.

Queued Human Review is not an execution failure:

```text
scheduled pipeline -> ReviewCase QUEUED -> workflow SUCCESS
human reviews privately at localhost /review
later scheduled pipeline -> Publisher consumes eligible resolved case
```

The workflow never exposes the local Review UI or creates decisions. Hosted pull-request CI remains
separate and uses only a disposable PostgreSQL database; the trusted scheduled workflow uses the
persistent database and raw storage outside its checkout.

## Operational monitoring workflow

```text
PipelineRun / PipelineStageRun history
  -> deterministic source health evaluation
       -> stale RUNNING detection
       -> latest success/failure freshness
       -> recent per-stage duration trends
       -> queued Human Review references
  -> failed/stale condition candidates
  -> SHA-256 deduplication per source + condition + channel
  -> local LOG and optional external JSONL notification
  -> read-only /operations and operational-status APIs
```

The trusted scheduled workflow always runs this monitor after the pipeline attempt and subsequently
returns the original pipeline exit code. Monitoring therefore cannot make a failed pipeline appear
successful. Repeated evaluation of the same condition reuses the stored notification identity and
does not redeliver it; a distinct failed run or a new stale-success boundary can notify again.

Monitoring is observational. It does not start pipelines, resolve ReviewCases, alter Candidate or
Master data, or expose the private Review UI. `--dry-run` predicts health and notification routing
without writing notification history. Normal monitoring may write only immutable operational
notification audit records and an optional local external JSONL sink.

## Public Recruitment read workflow

```text
public GET request
  -> ACTIVE RecruitmentMaster only
  -> validate current revision belongs to that master
  -> current immutable MasterFields only
  -> derive application status for the requested/current UTC date
  -> apply approved-field filters and deterministic ordering
  -> bounded public summary/detail response
```

No CandidateRevision enters the public contract directly. Drafts, unresolved or rejected review
work, and verified/confident data that has not crossed the Master Publisher boundary remain absent.
Historical Master revisions remain available only through internal APIs and do not appear in a
public detail response after a newer revision becomes current.

Public provenance is composed from the source document and registered endpoint behind each current
MasterField. The response keeps the original source URL, document type, endpoint name, source class,
and authority identity, but omits evidence text, raw storage, reviewer data, internal verification
and confidence records, hashes, changes, and operational history. Every public route is GET-only;
T-017 performs no publishing or other state transition.

## Public Recruitment website workflow

```text
GET /jobs or /jobs/{master_id}
  -> T-017 PublicRecruitmentService
  -> ACTIVE current RecruitmentMaster DTOs only
  -> presentation-only view formatting
  -> escaped server-rendered HTML
  -> safe explicit official-source links
```

Browse filters and pagination are ordinary GET query parameters and therefore remain bookmarkable
and read-only. Detail pages render typed approved values without exposing Candidate, Evidence,
Verification, Confidence, Review, MasterChange, publication-event, or operational records.
Templates never query the database and never derive approval or confidence.

An empty page is a valid trusted state when no RecruitmentMaster has been published. The interface
does not promote the existing queued APSC ReviewCase, trigger the Publisher, or manufacture sample
public data. Human Review and operations remain separate private/local interfaces.

## Public release workflow

```text
Internet client
  -> TLS-terminating reverse proxy / edge request limits
  -> loopback/private container port
  -> app.public_main trusted-host and security middleware
       -> /jobs or /api/public/v1 only
       -> current ACTIVE RecruitmentMaster read
       -> body-derived ETag + must-revalidate cache policy
  -> response

private operator network
  -> app.main
       -> /review, /operations, and /api/v1
```

`app.public_main` does not mount the private routes, so proxy configuration cannot accidentally
make them reachable through the public process. Health probes disclose only `ok` or `unavailable`.
The public database role is read-only and migrations continue through the trusted administration
runtime.

Release preparation builds an immutable public container, applies migrations through the trusted
runtime, runs fixture-based tests and the public smoke script, then switches the reverse proxy to
the new container. Rollback restores the prior container image; database/raw-storage restoration is
used only for data-loss recovery and follows the documented coordinated backup procedure. Public
cache revalidation prevents a prior Master representation from masking a newly published current
revision.

## Controlled public release workflow

```text
manual Public Release dispatch
  -> GitHub-hosted Ubuntu build
       -> immutable sha image
       -> HIGH/CRITICAL vulnerability gate
       -> GHCR push + provenance attestation
  -> protected public-production approval
  -> trusted Windows Docker host
       -> coordinated PostgreSQL + raw backup
       -> pull immutable image
       -> Caddy TLS / explicit public path routing
       -> public container readiness
       -> public/private smoke gate
       -> append external release audit
       -> rollback to previous image on failure
```

The workflow never deploys from pull-request code and never exposes `app.main`. Credential values
come only from protected Environment secrets and are masked; the checkout remains disposable.
Credential rotation deploys and health-checks the replacement public-reader secret before the old
role is revoked.

```text
scheduled public availability
  -> healthz / readyz / jobs
  -> verify private paths remain 404

manual restore rehearsal
  -> explicit coordinated backup
  -> random isolated PostgreSQL database
  -> Alembic + raw-reference checks
  -> guaranteed temporary database removal
```

Neither availability nor restore validation changes recruitment or review state. Deployment does
not publish Master data; it only serves Master records already approved by the trusted pipeline.

## Confidence V2 routing to Post-aware Master

```text
finalized VerificationRun
  -> immutable Confidence V2 assessment
  -> immutable independent Routing V1 assessment
       -> no semantic risk: shared publisher may publish directly
       -> semantic risk: routing-linked ReviewCase
            -> Advertisement-wide decision blocks all Posts
            -> Post field decision blocks only that Post
            -> valid sibling Post proceeds unchanged
  -> immutable Master revision + approved Master fields
       -> ordered MasterPost snapshots
       -> MasterPostFact provenance links
```

The verification worker creates the Confidence V2/routing pair and queues the routing-linked case
when required. The Master Publisher worker prefers V2 whenever it exists and otherwise processes
historical V1. Pending or cancelled routed review is skipped safely. Resolved review is projected by
scope, and every stored review snapshot is checked against re-derived confidence and routing inputs
before Master writes occur. API replay returns the existing publication event and revision.
