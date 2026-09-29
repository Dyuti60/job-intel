# Next task: Master Publisher incremental scan optimization

The staged 11-source activation was correct and release-ready, but each later source run rescanned
the growing unresolved Publisher backlog (up to 92 assessments). Design the smallest deterministic
incremental selection/batching change that avoids repeatedly scanning unchanged `REVIEW_PENDING`
assessments while preserving:

- immutable Verification, Review, publication events, and Master history;
- prompt publication after a Review decision or newly verified direct-publication assessment;
- idempotency and stable Post/Master identity;
- per-record failure isolation and existing scheduler semantics;
- explicit metrics for selected, skipped, published, unchanged, and failed assessments.

Do not weaken Review/Public Readiness safeguards, auto-approve pending work, expand source coverage,
or combine this with Review UX changes. Add focused Publisher tests and benchmark the scan selection
against the current persisted backlog before any production activation.
