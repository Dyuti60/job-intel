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
