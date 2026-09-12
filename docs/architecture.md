# Architecture

## Purpose and boundaries

Assam Job Intelligence is a trustworthy master-data platform for Assam Government recruitment
information. It turns official source material into evidence-backed, reviewed, approved records.
Eligibility search, user profiles, tracking, alerts, SEO, exam preparation, payments, and national
recruitment are downstream or out of scope.

Official government and recruiting-authority sources are authoritative. Secondary sources can aid
discovery and cross-checking but cannot displace official evidence.

## Conceptual pipeline

```text
Source Registry
  -> Discovery Run
  -> Source Document
  -> Recruitment Candidate
  -> Recruitment Candidate Revision
  -> Candidate Field
  -> Evidence
  -> Verification
  -> Human Review
  -> Approval
  -> Master Publisher
  -> Recruitment Master
```

The pipeline has a deliberate trust boundary:

- **Raw/discovery data:** registry observations, runs, fetched documents, extracted candidates,
  claims, evidence, and verification results. It preserves what was observed and how it was derived.
- **Cleansed/approved master data:** only approved and publishable recruitment information. Master
  changes retain prior values and an audit trail.

Discovery is never a direct Job Master writer.

## Components and responsibilities

- **Source Registry (implemented in T-002):** persistent inventory of Assam recruiting authorities
  and their explicitly registered endpoints. It records endpoint purpose, authority classification,
  operational state, whether discovery is permitted, optional adapter selection, last verification
  time, and registry provenance. Official, supporting-government, and secondary/discovery-only
  sources are distinguished explicitly. Registry provenance describes why an endpoint is trusted
  or retained; it is not recruitment Evidence.
- **Discovery:** independently replaceable adapters inspect registered sources, record runs, retain
  source documents, detect changes, and propose recruitment candidates. Repeat runs are idempotent.
- **Verification:** independently evaluates candidate field claims against evidence, applying
  deterministic rules wherever possible and producing explainable outcomes.
- **Human Review:** resolves conflicts and handles missing, stale, low-confidence, or critical facts.
  Corrections and decisions are attributable and auditable.
- **Approval:** marks a verified/reviewed revision as publishable. Approval is an explicit boundary,
  not a side effect of discovery.
- **Master Publisher:** idempotently applies approved revisions; it cannot silently overwrite master
  data and must create change history.
- **PostgreSQL Job Master:** authoritative current view of approved Assam recruitment data.
- **Audit/change history:** immutable or append-oriented trace of source observations, decisions,
  approvals, publication events, and old/new master values.
- **Future consumers:** eligibility search, public job search, user profiles, tracking, SEO, alerts,
  and ASSAM_EXAM_AI consume the master but do not own its truth lifecycle.

## Domain layers

The API layer handles transport and schemas. Services coordinate use cases and state transitions.
Domain-oriented packages hold future discovery, verification, review, and publishing behavior.
Repositories isolate persistence. SQLAlchemy models map persistent state. Source adapters isolate
external site behavior. Configuration, logging, and database setup remain infrastructure concerns.

External AI, if later justified, remains an optional provider behind an interface. Crawling, hashing,
deduplication, dates, state transitions, and publication safeguards remain deterministic.

## Implemented Source Registry

`RecruitingAuthority` owns one or more `SourceEndpoint` records. Stable, unique authority codes
support future configuration and adapter selection. Canonical endpoint URLs are normalized
conservatively and globally unique. Enum-backed database checks constrain authority type/status and
endpoint type/class/status. Foreign keys use restricted deletion because deactivation is the normal
operational lifecycle and registered provenance must not disappear casually.

The registry sits before Discovery as an allow-list and trust-classification boundary. Future
Discovery workers may enumerate only registered endpoints that satisfy explicit eligibility policy,
including active authority and endpoint state plus `discovery_enabled=true`. Registration does not
fetch a URL, assert a recruitment fact, create Evidence, or permit direct Job Master writes.

## Discovery execution and source-document provenance

T-003 implements the raw/discovery segment:

```text
SourceEndpoint -> DiscoveryRun -> DiscoveryObservation -> SourceDocument
```

A `DiscoveryRun` is one execution attempt against an eligible registered endpoint. It records its
manual, scheduled, or retry trigger; start and completion times; deterministic counters; terminal
status; and optional failure details. Runs and their counters are service-managed. Registry
deactivation prevents new runs but does not hide or delete historical execution data.

A `SourceDocument` is an immutable content version identified within one endpoint by:

```text
(source_endpoint_id, normalized_document_url, SHA-256 content_hash)
```

The exact observed URL is retained separately from the conservatively normalized identity URL.
Seeing the same URL/hash updates only sighting metadata and its latest-run reference. A different
hash at the same normalized URL creates another version; the previous hash and version remain
unchanged. Identical bytes at different URLs remain distinct observations. Database uniqueness
protects version identity.

`DiscoveryObservation` is the many-run history connecting runs to document versions. It records
NEW, UNCHANGED, CHANGED, or future UNAVAILABLE classification, exact observed URL, observation and
retrieval times, and response/content metadata. The run/document pair is unique, making repeated
controlled recording within one run idempotent.

T-003 stores metadata, SHA-256 identity, and a nullable provider-neutral `storage_uri`; it does not
store arbitrary large payloads in PostgreSQL or select an object-storage provider. A later fetcher
may persist raw bytes in local or object storage and attach that location while keeping content
identity and observation provenance in PostgreSQL.

Source documents remain raw evidence inputs, not Recruitment Candidates or Evidence claims.
Future candidate fields will reference document versions so extraction can be reproduced and
Verification can evaluate provenance without mutating raw document identity.

## Recruitment candidates and extracted fields

T-004 extends the raw/untrusted side of the pipeline:

```text
SourceDocument
  -> RecruitmentCandidate
  -> RecruitmentCandidateRevision
  -> CandidateField
  -> future Evidence and Verification
```

A `RecruitmentCandidate` is a logical proposal identified by
`(recruiting_authority_id, candidate_key)`. Candidate keys are normalized uppercase stable
identifiers; recruitment titles are display metadata and never define identity. Candidate status is
limited to DRAFT, READY_FOR_VERIFICATION, and DISCARDED. These states do not assert truth.

Each `RecruitmentCandidateRevision` is an immutable structured extraction from exactly one
immutable `SourceDocument` version. Revision numbers increase per candidate. The deterministic
revision hash is SHA-256 over UTF-8 canonical JSON containing the source-document UUID and content
hash plus fields sorted by path, with each field's path, declared value type, and normalized
structured value. JSON keys are sorted and compact separators are used. Raw text, source locators,
extraction notes/methods, and timestamps are intentionally excluded from identity.

Equivalent structured input from the same document reuses the existing candidate revision.
Different structured values or a different source-document version create the next revision and
leave all earlier revisions and fields unchanged.

`CandidateField` uses a validated path-like identifier and an explicit STRING, INTEGER, DECIMAL,
BOOLEAN, DATE, DATETIME, JSON, or NULL type. Structured values use JSONB in PostgreSQL. Decimal
values are canonical finite strings, dates are ISO dates, datetimes are normalized to UTC, strings
use Unicode NFC, and JSON is canonicalized before hashing. Optional raw extracted text and an
uninterpreted provider-neutral source locator preserve extraction context.

Every field repeats the exact source-document reference and a composite foreign key enforces that it
matches its owning revision's source. Service validation also ensures the candidate authority
matches the source document endpoint's authority and rejects unavailable or failed documents.

Candidates, revisions, and fields remain unverified proposals. READY_FOR_VERIFICATION means only
that a candidate has at least one structured revision ready to enter a future verification process;
it is not verified, approved, publishable, or master data.

## Candidate evidence and extraction provenance

T-005 adds immutable extraction provenance after `CandidateField` and before independent
Verification. An `Evidence` record retains one bounded piece of source context from exactly one
immutable `SourceDocument` version. Its type is TEXT_EXCERPT, TABLE_FRAGMENT,
STRUCTURED_FRAGMENT, DOCUMENT_METADATA, or OTHER; its provider-neutral locator is stored without
interpretation. Excerpts are limited to 8,000 characters and optional surrounding context to
16,000 characters. Evidence is not raw-document storage: complete source artifacts remain behind
the T-003 provider-neutral `storage_uri` boundary.

Evidence identity is SHA-256 over UTF-8 canonical JSON containing the source-document UUID and
content hash, evidence type, normalized locator, excerpt, and context. Text uses Unicode NFC,
CRLF/CR line endings become LF, and surrounding whitespace is trimmed without collapsing internal
formatting. Locator normalization trims only surrounding whitespace. UUIDs, timestamps, and field
links are excluded. The unique `(source_document_id, evidence_hash)` key makes equivalent recording
idempotent while keeping evidence from changed document versions distinct. Evidence has no mutation
API; corrections create a separate historical record.

`CandidateFieldEvidence` is an explicit many-to-many association: one passage may support several
fields, and one field may retain several passages. It repeats `source_document_id`, and composite
restricted foreign keys to both parents enforce that an extraction-evidence link cannot cross the
single-document boundary of its candidate revision. Duplicate field/evidence links are prevented
and idempotently reused.

Evidence answers which captured source context supports an extracted candidate value. **Evidence
does not establish truth.** It does not verify a value, weight source authority, calculate
confidence, resolve conflicts, change candidate readiness, or make data publishable. Those remain
responsibilities of later Verification, review, approval, and master-publication domains.

## Independent field verification

T-006 implements the independent verification segment:

```text
RecruitmentCandidateRevision snapshot
  -> VerificationRun
  -> FieldVerification snapshot
  -> VerificationEvidenceAssessment
  -> deterministic outcome and findings
```

A `VerificationRun` targets exactly one immutable candidate revision and snapshots its revision
hash. It starts PENDING, explicitly moves to RUNNING, and terminates as COMPLETED, PARTIAL, or
FAILED. The service checks the snapshot before execution mutations. `fields_total` is the number of
CandidateFields in the target revision; outcome counters count finalized field results and are
service-managed. COMPLETED requires every field to be finalized, while PARTIAL requires at least
one but not all fields.

Each `FieldVerification` snapshots the field path, declared type, and normalized structured value.
It starts PENDING while assessments are collected and becomes FINALIZED exactly once. The unique
run/field identity prevents duplicate results. Finalized field results, their counts, reason, and
finding are immutable; re-verification creates a new VerificationRun instead of rewriting history.

`VerificationEvidenceAssessment` classifies persisted Evidence as SUPPORTS, CONTRADICTS, or
CONTEXT_ONLY for one field result. It may optionally retain a normalized typed asserted value. A
supplied SUPPORTS value must equal the field snapshot, while a supplied CONTRADICTS value must
differ. Evidence may come from the extraction document, another immutable version, another
endpoint, or another registered authority. This intentionally differs from T-005 extraction links,
which require the same SourceDocument.

The client cannot supply source authority. Verification derives SourceClass through
`Evidence -> SourceDocument -> SourceEndpoint` and snapshots that class on the assessment. API
composition exposes the assessment, Evidence excerpt/locator, SourceDocument, SourceEndpoint, and
source class without duplicating full Evidence content in verification storage.

The deterministic V0 policy is ordered as follows:

1. Any authoritative-official contradiction produces CONFLICT / AUTHORITATIVE_CONFLICT.
2. Otherwise, authoritative-official support produces CONFIRMED / AUTHORITATIVE_SUPPORT, while
   weaker contradictions remain visible in findings.
3. Without authoritative support, any combination of non-authoritative support and contradiction
   produces CONFLICT / SOURCE_CONFLICT.
4. No assessments produce INSUFFICIENT_EVIDENCE / NO_EVIDENCE.
5. Secondary support alone produces INSUFFICIENT_EVIDENCE / ONLY_SECONDARY_EVIDENCE.
6. Context-only, supporting-only, contradiction-only, and other inconclusive inputs produce
   INSUFFICIENT_EVIDENCE / INSUFFICIENT_SUPPORT.
7. NOT_APPLICABLE is never inferred; an explicit finalization request produces NOT_APPLICABLE /
   MANUALLY_MARKED_NOT_APPLICABLE.

T-006 stores source-class support and contradiction counts, total evidence evaluated, explicit
reason codes, and human-readable findings. It deliberately stores no numeric confidence score.
Verification never mutates candidates, revisions, fields, extraction links, Evidence, or source
documents, and it does not approve or publish data.

## Explainable confidence and review routing

T-007 adds immutable `FieldConfidenceAssessment` and `RevisionConfidenceAssessment` records after
Verification. Confidence means how strongly persisted verification facts support a CandidateField
value's reliability. It is not a statistically calibrated probability, eligibility percentage,
job-match score, approval, or publication decision.

Every assessment records policy version `V1`, a SHA-256 fingerprint of its immutable inputs, the
result, machine-readable review reasons, and a JSONB component breakdown. A field/policy pair and a
verification-run/policy pair are each unique. Replaying the same calculation returns the existing
record; a fingerprint mismatch reports an integrity conflict. A later algorithm must use a new
policy version and create new historical assessments rather than reinterpret or overwrite V1.

V1 field scores start from the finalized verification reason: authoritative support 90,
authoritative conflict 15, source conflict 35, no evidence 20, secondary-only evidence 45, and
other insufficient support 40. NOT_APPLICABLE has no reliability score and is excluded from score
averaging. Distinct source endpoints, derived through
`VerificationEvidenceAssessment -> Evidence -> SourceDocument -> SourceEndpoint`, drive modifiers:
additional authoritative support is +3 each capped at +6; official supporting support is +2 each
capped at +4; secondary support is +1 each capped at +2; secondary contradiction is -5 each capped
at -10; and official supporting contradiction is -12 each capped at -24. Repeated Evidence from
one endpoint cannot multiply a source bonus or penalty. Scores are clamped to 0..100, and an
authoritative-conflict result is additionally capped at 25.

The breakdown records the anchor, every capped modifier, distinct usable/context endpoint counts,
authoritative-support presence, extraction-evidence availability, thresholds, and final score.
These completeness facts are explainable inputs; V1 does not blindly reward raw evidence volume.

Field criticality is policy-derived, never client supplied. V1 classifies known application
start/end/deadline and application-URL paths, age limits/cutoffs/relaxations, qualification,
domicile, experience, vacancies, and indexed post eligibility/vacancy paths as CRITICAL. Unknown
paths default to STANDARD. Defaults configured through `AJI_CONFIDENCE_STANDARD_THRESHOLD`,
`AJI_CONFIDENCE_CRITICAL_THRESHOLD`, and `AJI_CONFIDENCE_REVISION_THRESHOLD` are 80, 90, and 85.
Thresholds affect deterministic routing, not the score algorithm, and are captured in the input
fingerprint and breakdown.

Conflicts and insufficient evidence always require review. A score below its standard/critical
threshold requires review, and every critical field without authoritative-official support requires
review regardless of its numeric score. Priorities are NONE, NORMAL, HIGH, and CRITICAL:
authoritative conflict on a critical field is CRITICAL; other authoritative conflict, critical
source conflict, critical missing authoritative support, and a very low critical score are HIGH;
other review conditions are NORMAL.

Revision confidence is scoped to one COMPLETED or PARTIAL VerificationRun. It weights CRITICAL
scores by 2 and STANDARD scores by 1, excludes NOT_APPLICABLE scores, and multiplies the weighted
average by `finalized fields / total revision fields`. Rounding is deterministic half-up to an
integer. A partial run, any field requiring review, any authoritative conflict, or a revision score
below threshold routes the revision to review; revision priority is the maximum field/aggregate
severity. A high average can therefore never hide a dangerous low-confidence critical field.

Confidence calculation only creates T-007 records. It never mutates VerificationRun,
FieldVerification, VerificationEvidenceAssessment, Evidence, CandidateField, or CandidateRevision.
Confidence does not approve data, and high confidence does not itself publish data. Human Review
records and decisions remain a later domain.

## Human Review decision layer

T-008 implements Human Review as a separate, append-oriented decision domain:

```text
RevisionConfidenceAssessment
  -> ReviewCase
  -> FIELD and/or REVISION ReviewItems
  -> immutable ReviewDecisions
  -> approved projection preview
  -> future Master Publisher
```

A `ReviewCase` is the workload for exactly one RevisionConfidenceAssessment, VerificationRun, and
CandidateRevision. The revision confidence score, priority, policy version, review reasons, and
component breakdown are copied into immutable review snapshots. Database uniqueness permits only
one case per revision-confidence assessment; a newer verification run and confidence assessment
creates a separate historical case rather than merging review history.

Queue generation accepts only assessments with `review_required=true` and first revalidates T-007
input fingerprints and deterministic output against persisted Verification facts using the policy
thresholds captured in the confidence breakdown. Every routed FieldConfidenceAssessment produces
one FIELD item. A single consolidated REVISION item is added when the revision assessment contains
PARTIAL_VERIFICATION or REVISION_SCORE_BELOW_THRESHOLD. The stable per-case item keys prevent
duplicate field or revision work on replay.

FIELD items snapshot the CandidateField path, type, and value plus field confidence score,
priority, policy, reasons, and breakdown. They retain references to CandidateField,
FieldConfidenceAssessment, and FieldVerification so a future UI can retrieve extraction Evidence,
verification assessments, source documents, endpoints, and source classes without copying source
text into decisions. REVISION items omit field references and snapshot the aggregate confidence
facts that require whole-revision judgment.

Cases transition QUEUED -> IN_REVIEW -> RESOLVED, or QUEUED/IN_REVIEW -> CANCELLED. Decisions
require an IN_REVIEW case. Each item transitions PENDING -> RESOLVED exactly once and has at most
one immutable `ReviewDecision`. The final item decision automatically resolves the case. Resolved
and cancelled cases reject new decisions, and a changed conclusion requires a new VerificationRun,
confidence assessment, and ReviewCase.

Review decisions are APPROVE_AS_IS, CORRECT_AND_APPROVE, REJECT, or REQUEST_REVERIFICATION.
Revision items cannot be corrected. Field corrections must use the CandidateField's existing value
type, pass the T-004 deterministic normalizer, and differ from the original value. The decision
stores original value/type snapshots, normalized corrected value/type where applicable, bounded
reviewer identity, required decision notes for correction/rejection/reverification, optional
evidence note, and decision time. A correction never rewrites CandidateField or CandidateRevision.

Resolved case outcome precedence is deterministic: any REQUEST_REVERIFICATION produces
REVERIFICATION_REQUESTED; otherwise any REJECT produces REJECTED; otherwise any correction produces
APPROVED_WITH_CORRECTIONS; otherwise all approve-as-is decisions produce APPROVED.

The approved projection endpoint is an internal, non-persistent preview. For APPROVED cases it
uses original CandidateField values, including fields that did not require review. For
APPROVED_WITH_CORRECTIONS it substitutes only normalized decision values and retains original and
decision references. REJECTED and REVERIFICATION_REQUESTED cases return
`master_eligible=false`, mark every field unapproved, and expose no effective publishable values.
This projection is not Recruitment Master, does not publish anything, and does not create an
approval or master record.

Human Review never mutates candidate, Evidence, Verification, or Confidence history. Reviewer
decisions and snapshots provide the audit layer, while authentication, assignments, a browser UI,
formal approval, and Master publication remain future capabilities.

## Local Human Review web layer

T-009 adds a server-rendered presentation layer at `/review` over the T-008 Human Review domain.
FastAPI routes render Jinja2 templates, accept small standard URL-encoded forms, and use
Post/Redirect/Get after mutations. Queue and case screens call `ReviewService` for lifecycle and
decision changes; templates contain no transition, correction, confidence, verification, or
projection policy.

`ReviewCaseViewService` is a read-only composition boundary for the UI. It assembles retained
candidate and authority identity, source-document metadata, field and revision confidence
snapshots, extraction Evidence, VerificationEvidenceAssessments, SourceEndpoint/source-class
provenance, review progress, immutable decisions, and the T-008 approved projection. It formats
typed values and stored confidence components for display but never recalculates scores or makes
domain decisions.

Evidence excerpts and context are rendered as escaped text, never executable source HTML.
Registered source URLs are explicit new-window links with `noopener noreferrer`; remote pages are
not embedded. All lifecycle and decision mutations use POST, while GET routes remain read-only.

This interface is a localhost development tool. T-009 deliberately provides no authentication,
authorization, CSRF protection, hardened sessions, assignment workflow, or production deployment
controls. Those protections are mandatory before deployment to a shared or untrusted network.
The resolved-case projection remains a non-persistent preview: the web layer does not approve,
publish, or create Recruitment Master data.

## Approved Recruitment Master and deterministic Publisher

T-010 adds the trusted-data boundary after Verification, Confidence, and, when required, Human
Review. `RecruitmentMaster` is the stable identity for one normalized
`(recruiting_authority_id, candidate_key)` and stores its display name, ACTIVE/INACTIVE/ARCHIVED
status, restricted current-revision reference, first/last publication timestamps, and the latest
successful trustworthy verification time. A different candidate key remains a different
recruitment cycle.

Every business-content change creates an immutable `RecruitmentMasterRevision`. Revisions are
numbered monotonically per master and record the exact CandidateRevision, VerificationRun,
RevisionConfidenceAssessment, optional ReviewCase, publication path, display name, publication
time, and verification time. The allowed paths are VERIFIED_NO_REVIEW, HUMAN_APPROVED, and
HUMAN_CORRECTED. The master current-revision pointer makes current reads direct while older
revisions remain retained.

`MasterField` stores the normalized T-004 typed value for one unique field path in a master
revision. It always references its source CandidateField. Its value origin distinguishes
CANDIDATE_VERIFIED, HUMAN_APPROVED_AS_IS, and HUMAN_CORRECTED; human-derived values additionally
reference the immutable ReviewDecision. A corrected value is copied into the master field without
rewriting the original CandidateField or any review history.

The Publisher accepts a specific RevisionConfidenceAssessment, so it never guesses among multiple
VerificationRuns or policy versions. Direct publication requires a READY_FOR_VERIFICATION
candidate, a COMPLETED run, complete finalized field verification/confidence coverage, matching
revision and field snapshots, a valid confidence fingerprint, and `review_required=false`. When
review is required, direct publication is impossible: the unique matching ReviewCase must be
RESOLVED as APPROVED or APPROVED_WITH_CORRECTIONS, its snapshots must still match Confidence, and
the existing T-008 approved projection must report `master_eligible=true`. Rejected, cancelled,
unresolved, or reverification-requested cases cannot publish.

The projection hash is lowercase SHA-256 over deterministic canonical JSON containing the
authority code, normalized candidate key, display name, and field entries sorted by path. Each
entry contains its path, declared type, and normalized structured value. UUIDs, timestamps,
reviewer notes, and request metadata do not affect business identity. Display name intentionally
participates because it is published master data. A master/hash uniqueness constraint protects
concurrent duplicate revisions.

If the projection changes, publication creates the next immutable revision and `MasterChange`
records for ADDED, UPDATED, and REMOVED fields. First publication records every field as ADDED.
Changes snapshot old/new types and values and retain the new CandidateField and optional
ReviewDecision provenance. If independently reverified source provenance yields the same effective
projection, no business revision, fields, or changes are duplicated.

Every successful distinct confidence-based publication attempt creates an immutable
`MasterPublicationEvent`, classified CREATED or UNCHANGED, linking the selected candidate revision,
verification run, confidence assessment, optional review case, publication path, and reused or new
master revision. Exact request replay reuses the existing event. An UNCHANGED event refreshes only
the logical master's `last_verified_at`; historical revision timestamps remain immutable.

Publication runs in one database transaction. Master, revision, fields, changes, event, and current
pointer either persist together or roll back together. The Master API is internal and read-only
apart from the focused Publisher operation. It exposes current state, immutable revisions,
field-level provenance, changes, and publication events; it is not the future public job-search
contract.

## Executable Master Publisher worker

T-010B adds an independently executable orchestration layer at
`python -m workers.master_publisher`. It does not own projection, eligibility, integrity,
transaction, correction, hashing, revision, or change semantics. Those remain exclusively in the
T-010 `MasterPublisherService`.

`RevisionConfidenceRepository.list_pending_publication_ids` selects only assessments attached to
COMPLETED VerificationRuns and without a successful MasterPublicationEvent. Selection is ordered by
assessment creation time and UUID, then limited by `AJI_MASTER_PUBLISHER_BATCH_SIZE` (default 100).
This makes batching deterministic and prevents an unchanged periodic invocation from replaying
already-processed inputs or generating repeated UNCHANGED events.

The worker classifies required-review state before publishing. Direct assessments and RESOLVED
APPROVED/APPROVED_WITH_CORRECTIONS cases are delegated to `MasterPublisherService`; missing,
queued, in-review, cancelled, rejected, and reverification-requested cases are reported and skipped.
A domain/integrity failure rolls back that assessment and does not prevent later IDs in the batch
from being processed. Database-level failure remains a worker-level error. Each real publication
retains the Publisher's own atomic transaction rather than joining the batch into one transaction.

Dry-run uses the Publisher's read-only preview path. It revalidates the same immutable inputs,
constructs the same effective projection/hash, and reports whether content would create, update, or
reuse a MasterRevision, then rolls back without Master mutations. T-010B adds no scheduler, queue
broker, or database schema.

## First live official-source adapter: APSC

T-011 adds a narrow `APSCRecruitmentAdapter` for Advertisement 12/2026, Research Assistant under
the Labour Welfare Department. Idempotent registry setup ensures an ACTIVE APSC COMMISSION and its
ACTIVE, discovery-enabled APPLICATION_PORTAL at `https://apscrecruitment.in/`, classified
`AUTHORITATIVE_OFFICIAL` with adapter key `apsc_recruitment`. Compatible rows are reused;
conflicting manually maintained metadata is rejected rather than overwritten.

The adapter performs only three official reads: portal HTML, the public
`server/api/Advertisement/WhatsNew` JSON feed, and the official Advertisement 12/2026 PDF. The
feed may no longer list a closed recruitment, so the stable official PDF is the narrow detailed
source. No third-party page supplies CandidateFields. HTTPX uses explicit timeouts, redirects, an
identifying user agent, OS trust-store TLS validation, a size ceiling, media-type checks, and two
transient-only retries for network errors, 429, and 5xx.

Exact bytes are SHA-256 hashed before existing T-003 observation handling. Content-addressed
development storage writes below `data/raw/apsc/YYYY/MM/` and persists portable `raw://` URIs;
PostgreSQL stores metadata rather than arbitrary raw bodies. Identical bytes reuse file/document
identity. Changed bytes preserve the old SourceDocument. Dry-run executes the same domain workflow
inside a rollback-only unit of work and performs no raw-file write.

The parser is specific to the selected portal card and text-based PDF. It uses deterministic
labels and pypdf without OCR. Only supported fields with bounded official context pass through the
T-004 typed validators, and every field links to T-005 Evidence on the exact extraction document.
The deterministic candidate key is `APSC_ADVT_12_2026`; SourceDocument identity remains in the
revision hash, preserving changed provenance as immutable revisions.

The worker composes existing Registry, Discovery, Candidate, and Evidence services in one
transaction and stops at extraction Evidence. It never creates Verification, Confidence, Review,
or Master records. Authoritative extraction remains unverified Candidate data.

## Automated Verification and Confidence worker

T-012 adds a one-shot orchestration service and `python -m workers.verification` entry point over
the existing T-004 through T-008 domains. It selects non-discarded CandidateRevisions with fields
in stable creation-time/UUID order, scoped by authority and optional candidate key. A completed V1
VerificationRun with its RevisionConfidenceAssessment makes that revision current and prevents
repeat work. A resolved `REVERIFICATION_REQUESTED` case becomes eligible exactly once when no newer
run exists. Batch size is configured by `AJI_VERIFICATION_BATCH_SIZE` (default 100).

The worker is downstream-only: it imports no discovery adapter or HTTP client and reads only
persisted CandidateFieldEvidence and immutable Evidence. A focused deterministic interpreter
compares NFC/case/whitespace-normalized strings, field-labelled integers, and bounded DD/MM/YYYY,
DD-MM-YYYY, or ISO dates. Unsupported or ambiguous input becomes `CONTEXT_ONLY`; absent evidence
finalizes through T-006 as
`INSUFFICIENT_EVIDENCE / NO_EVIDENCE`. Stored Evidence is never rewritten.

Each selected revision is one transaction. DRAFT readiness changes use CandidateService;
VerificationRun, FieldVerification, assessment, finalization, and completion use
VerificationService; ConfidenceService calculates the unchanged V1 policy; and ReviewService
creates a QUEUED case only when routing requires it. A failure rolls back that revision and later
items continue. Dry-run executes the same domain path and rolls back every revision. No Human
Review decision or Recruitment Master publication occurs here.

## End-to-end pipeline orchestrator

T-013 adds `python -m workers.pipeline` as a coordination-only layer. A small explicit registry maps
the supported `APSC` source to authority code `APSC`. The orchestrator calls
APSCDiscoveryWorkerService, VerificationWorkerService, and MasterPublisherWorkerService in process
and consumes their structured summaries. It does not parse worker output or own discovery,
evidence interpretation, confidence, review, correction, eligibility, hashing, or publication
rules.

Stages remain independently transactional. Fatal Discovery or stage-level infrastructure failure
short-circuits unsafe downstream execution. A usable PARTIAL Discovery continues through valid
persisted work and makes the pipeline PARTIAL. Isolated Verification or Publisher item errors retain
their worker behavior and make the combined result PARTIAL. Queued Human Review is normal SUCCESS.

The Publisher always runs after a safely completed Verification stage, including when Discovery is
UNCHANGED and Verification scans zero revisions. Consequently an eligible ReviewCase resolved by a
human between executions is published by a later pipeline invocation without rediscovery or
reverification. Queued, in-review, rejected, cancelled, and reverification-requested cases retain
the existing Publisher safeguards.

Pipeline dry-run delegates to each existing stage's dry-run implementation. Each stage evaluates
the persisted state visible when it begins and rolls back its own writes; the orchestrator does not
maintain a separate hypothetical cross-stage database. T-013 adds no persistence, scheduler,
distributed lock, subprocess boundary, or recurring execution.

## Pipeline operational history and Continuous Integration

T-014 wraps the T-013 coordinator with an operational projection; it does not duplicate any stage
business logic. Each CLI invocation first creates one UUID `PipelineRun` in `RUNNING`, runs the
existing orchestrator in process, and then finalizes that record as `SUCCESS`, `PARTIAL`, or
`FAILED`. Source/authority codes, trigger, timestamps, duration, dry-run marker, routing/publication
counts, bounded failure metadata, and the structured combined summary are retained.

Each attempted `DISCOVERY`, `VERIFICATION`, and `MASTER_PUBLISHER` stage has one immutable
`PipelineStageRun` per parent run. It retains status, timing, structured summary, and bounded failure
metadata. Parent stage-status columns support efficient operations queries. Foreign keys use
`RESTRICT`; execution history is audit data, not a cascade-deletion target. Current `RUNNING` state
provides overlap-detection groundwork only. T-015 will combine it with an application/database guard
and GitHub Actions concurrency; T-014 does not claim a lock.

Dry-run deliberately has one exception to its no-write contract: operational PipelineRun and
PipelineStageRun history is committed. Discovery, Candidate, Verification, Confidence, Review, and
Master writes still use their existing rollback behavior. This makes dry-run observable without
changing recruitment data.

The read-only `/api/v1/pipeline-runs` and `/api/v1/pipeline-runs/{id}` endpoints expose newest-first
history and stage detail. They do not start, retry, cancel, or mutate pipeline executions.

Continuous Integration is separate from runtime operations. `.github/workflows/ci.yml` uses a
GitHub-hosted Ubuntu runner with read-only contents permission, Python 3.12, uv, and a temporary
PostgreSQL service. It applies the full migration chain, checks drift, runs fixture-only tests, and
Ruff. The disposable CI database/raw path are not the persistent local/V0 stores. CI never runs live
APSC Discovery; a trusted self-hosted scheduled runtime remains a T-015 concern.
