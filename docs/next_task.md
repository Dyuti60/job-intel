# T-016 — Operational Monitoring and Failure Notifications

T-016 should build a local/private operational monitoring layer from the persisted `PipelineRun`
and `PipelineStageRun` history created by T-014 and exercised by T-015.

It should include:

- deterministic stale/RUNNING and last-success/last-failure health evaluation
- source-level operational status and recent stage-duration trends
- bounded failure summaries without secrets or stack traces
- configurable local notification routing for failed or stale scheduled executions
- deduplicated notification events so repeated checks do not spam operators
- links/references to the relevant PipelineRun and queued Human Review workload
- a private read-only operational page or API suitable for local/V0 administration
- tests using controlled history without live APSC access

T-016 must reuse the existing pipeline and operational-history domains. It must NOT make Human
Review decisions, publish Recruitment Master records, expose the local UI publicly, or introduce a
distributed observability platform.

Do not implement T-016 now.
