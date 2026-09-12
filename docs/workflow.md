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
