# Assam Job Intelligence V1 execution plan

## Baseline inspected on 2026-09-14

- `main` and `origin/main` were both at `233944d`; the working tree was clean.
- Alembic was current at `20260912_0011` and reported no model/schema drift.
- The full baseline suite passed: 311 tests, Ruff, and `git diff --check`.
- Local PostgreSQL contained 18 advertisement-level candidates, 125 candidate fields, 19
  Confidence V1 assessments, 19 ReviewCases, and no published Master records.
- Existing deterministic live adapters cover APSC Advertisement 12/2026 and bounded archive
  discovery for SLPRB Assam, DEE Assam, and DME Assam.
- Existing runtime is advertisement-level from Candidate through Master and public jobs. The daily
  workflow schedules APSC only; the other three sources are manual choices.
- GitHub CLI is unavailable and no authenticated browser surface was exposed, so remote Actions and
  runner state must be verified after pushing by an available authenticated mechanism. Local
  workflow contract tests remain green.

## Delivery sequence

1. **Post domain foundation** — add immutable Advertisement revision/Post/Post Fact structure,
   evidence-compatible post scope, and an explicit legacy-unsplit representation without inventing
   historical splits.
2. **Deterministic multi-post extraction** — introduce shared advertisement facts, post-specific
   facts, reusable vacancy/section/table parsers, ambiguity capture, and fixture coverage.
3. **Confidence V2 and review routing** — preserve V1 rows, add deterministic V2 reliability
   scoring, and persist a separately versioned routing decision based on conflicts and ambiguity.
4. **Review and Post Master** — group review by advertisement and post, allow valid siblings to
   proceed, publish through one shared service from UI and CLI, and retain immutable provenance.
5. **Public post product and eligibility** — make approved Posts the public unit and evaluate
   versioned deterministic eligibility with field-level outcomes.
6. **Registry, adapters, backfill, and scheduling** — onboard a broad evidence-based Assam source
   inventory, reuse generic adapter families, backfill the inclusive two-year policy, and run due,
   grouped, selected, or all sources with isolation and bounded concurrency.
7. **Operations and production readiness** — bounded UI actions, monitoring, migrations, backup and
   restore validation, release isolation, live-source checks, CI repair, deployment evidence, and a
   final V1 report.

## Milestone gate

Each milestone requires focused tests, the full suite, Ruff, `git diff --check`, migration/drift
checks where applicable, diff self-review, truthful documentation, a separate commit, push, and
remote CI verification before proceeding. Live source checks are recorded separately and never
become CI dependencies.
