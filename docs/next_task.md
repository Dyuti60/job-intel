# T-014 — Scheduled Pipeline Execution and Operational Run History

T-014 should introduce controlled recurring execution for the end-to-end pipeline.

It should include:

- persistent PipelineRun history
- stage timing/status summaries
- scheduled one-shot invocation
- safe overlap prevention / locking
- source-level scheduling configuration
- retry/error visibility
- last-success/last-failure operational state
- ability to invoke the existing T-013 orchestrator without duplicating business logic

It must NOT introduce distributed infrastructure unless required.

For local/V0 operation prefer a lightweight scheduler or OS-compatible execution strategy.

Do not implement T-014 now.
