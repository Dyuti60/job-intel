# Next task: staged Assam production activation

Run the first controlled production cadence for the 11 enabled Assam sources:

- restore the configured PostgreSQL service at `localhost:5433` and confirm it is reachable;
- preview due sources and confirm the intended priority order;
- execute only the due set with normal persistence and existing locks;
- observe `/operations`, Review routing, and publisher outcomes through completion;
- reconcile READY/DEGRADED/BLOCKED results against `docs/assam_production_readiness.md`;
- stop and diagnose any BLOCKED source before retrying it.

Do not run a historical backfill, reactivate withheld sources, expand coverage, or change shared
Review/Master/Public behavior. This is an operational activation and observation task, not an adapter
development milestone.
