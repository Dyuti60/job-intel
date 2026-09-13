# V1-M4 — Post-grouped review and Post-aware Master

Make independent Routing V1 operational without mutating historical V1 ReviewCases or published
Master history.

The milestone should include:

- advertisement-grouped review with explicit Post sections and field provenance
- routing-driven review items that let valid sibling Posts proceed when another Post is blocked
- immutable approval/correction/rejection outcomes at the correct advertisement or Post scope
- one shared Post-aware publisher used by API, UI, and worker paths
- approved Advertisement/Post/PostFact Master revisions with old values and change history retained
- deterministic identity and replay behavior across corrected advertisements
- migration, API, UI, worker, integrity, idempotency, and rollback coverage

Do not publish directly from Confidence V2. Do not expose unapproved Posts publicly yet.
