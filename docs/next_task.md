# V1-M6 — Registry, adapter families, two-year backfill, and scheduling

Expand deterministic official-source coverage and operate it through one failure-isolated,
registry-driven scheduler.

The milestone should include:

- evidence-based inventory of high-value official Assam recruitment sources and onboarding status
- reusable deterministic HTML archive, link/PDF list, document-list CMS, and other justified adapter
  families with bounded fixtures and source-specific extensions
- inclusive current-year-plus-two-prior-calendar-years backfill without treating results, merit
  lists, admit cards, interviews, appointments, or similar lifecycle documents as new jobs
- registry scheduling metadata for enabled state, frequency/group, priority, adapter, rate bounds,
  last attempt, and last success
- CLI execution for one source, one group, all due sources, or all enabled sources, including dry-run
- deterministic ordering, per-source locks, failure isolation, retries/timeouts, audit history, and
  monitoring integration
- one bounded scheduled workflow rather than independent fragile cron workflows
- migration, adapter, scheduler, CLI, workflow, idempotency, rollback, and live-source validation

Do not blindly register URLs, overload Government sites, make CI depend on live sites, infer
recurrence from history, or introduce an LLM/agentic discovery runtime.
