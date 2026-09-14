# V1-M7 — Operations controls and production readiness

Complete the deterministic V1 operating surface and final evidence-backed readiness report.

- add bounded private UI actions for selected source, due sources, group, all enabled, dry-run,
  Publisher, and monitoring without accepting shell input
- preserve public/private route absence, CSRF-safe mutation behavior, per-source locks, and audit
- validate scheduler behavior against the local PostgreSQL runtime and perform the feasible
  two-year backfill for implemented sources without fabricating unsupported Posts
- reconcile source health, raw storage, backups/restores, Docker/public release, workflows,
  migration state, rollback, monitoring, and deployment prerequisites
- create the final V1 project report with implemented sources/families, actual historical coverage,
  test/CI/live-validation evidence, known limitations, deployment status, and explicit V2 deferrals

Do not expose operations publicly, run arbitrary commands from the UI, claim a backfill or
deployment that did not occur, or expand into agentic discovery.
