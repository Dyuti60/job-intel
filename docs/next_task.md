# T-017 — Public Recruitment Read API and Search Baseline

T-017 should introduce a stable, read-only public contract over current approved Recruitment Master
revisions for Assam Government recruitment discovery.

It should include:

- public list and detail APIs sourced only from ACTIVE RecruitmentMaster records and their current
  immutable revisions
- deterministic pagination, filtering, and ordering for authority, candidate identity, and selected
  approved structured fields
- safe derived application-date/status metadata without rewriting Master history
- a bounded public response that preserves useful official-source provenance while excluding
  internal operational, reviewer, and sensitive audit details
- explicit separation between public master reads and all candidate, verification, confidence,
  review, monitoring, and publisher mutation domains
- comprehensive tests proving that drafts, unresolved reviews, rejected data, historical non-current
  revisions, and operational records cannot leak into the public contract

T-017 must NOT implement a public browser UI, eligibility matching, user profiles, alerts,
preparation features, live crawling, automated Human Review, or mutable public APIs.

Do not implement T-017 now.
