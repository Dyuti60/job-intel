# T-012 — Automated Verification and Confidence Worker

T-012 should implement a one-shot worker that discovers CandidateRevisions ready for verification
and drives the existing:

Verification
→ FieldVerification
→ Confidence
→ Review routing

domains.

For the first APSC path it should use persisted official Evidence and Source provenance to produce
deterministic VerificationEvidenceAssessments without modifying Candidate history.

It should create ReviewCases automatically when T-007 reports `review_required=true`.

It must NOT make Human Review decisions automatically.

It should leave approved/no-review data ready for the existing T-010B Master Publisher.

Do not implement T-012 now.
