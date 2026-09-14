# Permanent implementation rules

These rules apply to all future work in this repository.

1. Scope is Assam Government recruitment and jobs only. Do not implement all-India support.
2. Official government and recruiting-authority sources are authoritative.
3. Secondary websites may assist discovery and cross-checking, but cannot override authoritative official evidence.
4. Discovery must never write directly to Job Master.
5. Discovery creates candidates, evidence, and discovery history.
6. Verification is independent of Discovery.
7. Verification evaluates candidate claims and fields against evidence.
8. Important fields must retain evidence and provenance.
9. Confidence must be explainable; it must not be an arbitrary LLM-generated percentage.
10. Conflicting, missing, stale, low-confidence, or critical information may require Human Review.
11. Human corrections and approval decisions must be auditable.
12. Only approved, publishable information may enter Job Master.
13. Approved master data must never be silently overwritten.
14. Master changes must preserve old values and history.
15. Discovery and publishing must be idempotent.
16. Repeating source discovery must not create duplicate recruitment master records.
17. Database schema changes require Alembic migrations.
18. Important application behavior requires automated tests.
19. Discovery adapters must remain independently replaceable and testable.
20. Never put secrets in source control; use environment-based configuration.
21. Do not implement preparation features inside the Job Intelligence domain.
22. Avoid coupling the architecture to a specific LLM provider.
23. Prefer deterministic code for crawling, hashing, deduplication, state transitions, deadlines, and other rule-based behavior.
24. External AI is optional and should be used only where it genuinely improves extraction or verification.
25. Keep raw/discovery data separate from cleansed/approved master data.
26. Advertisement is not Post; approved Post-level Master data is the canonical public job unit.
27. Missing optional facts and low confidence do not by themselves invalidate a recruitment.
28. Confidence, Review routing, and Publication policy are separate; policy versions are immutable.
29. Rejection never deletes immutable source, candidate, evidence, verification, or review history.
30. V1 must remain deterministic and LLM-independent; agentic Internet discovery is V2 scope.
31. Prefer reusable bounded adapter families and respectful, rate-limited crawling.
32. Scheduling must be idempotent, deterministically ordered, and failure-isolated by source.
33. Eligibility operates only on approved Post-level Master facts and is tied to an exact rule and
    Master revision.
34. Missing or ambiguous eligibility facts produce UNKNOWN or REVIEW_REQUIRED, never assumed
    eligibility.
35. Public runtime must not expose private Review, operations, Candidate, or audit capabilities.
36. Operational UI actions must invoke bounded services and never arbitrary shell commands.
37. Results, merit lists, admit cards, appointments, and similar lifecycle documents are not new
    jobs; historical advertisements do not imply recurrence.
38. Migrations and backfills must never fabricate unsupported Post splits or facts.
26. Advertisement and Post are distinct; one advertisement may produce multiple independently usable Posts.
27. The approved canonical Master and deterministic eligibility unit is a Post, with its parent Advertisement provenance retained.
28. Missing optional facts and low confidence do not by themselves invalidate a recruitment.
29. Confidence, Human Review routing, and publication policy are separate, versioned concerns; published policy versions are immutable.
30. Rejection never deletes source, evidence, candidate, review, or publication history.
31. Official facts must remain separate from derived intelligence.
32. V1 is deterministic and LLM-independent; agentic Internet discovery is future V2 scope.
33. Reuse bounded adapter families where practical, and crawl official sites respectfully with rate and timeout limits.
34. Scheduling and backfill must be idempotent and failure-isolated; historical advertisements never imply recurrence.
35. Results, merit lists, answer keys, appointment notices, and similar lifecycle documents are not new jobs.
36. Eligibility evaluates only approved Post Master revisions; missing or ambiguous requirements produce UNKNOWN or REVIEW_REQUIRED.
37. The public runtime must not expose private review, operations, audit internals, or mutation capabilities.
38. Operations UI actions must call bounded internal functions and must never execute arbitrary shell input.
39. Migrations and backfills must not fabricate unsupported post splits or facts.

## Codex Execution, Token, and Time Discipline

These rules prevent implementation sessions from wasting tokens or execution time while preserving
all correctness, trust, security, architecture, and engineering requirements above.

### 1. Scope-first execution

- Treat the user/Codex prompt as the scope boundary for every implementation task.
- Identify and inspect the smallest set of files and subsystems needed for the requested change.
- Expand inspection only when evidence from those files requires it.
- Do not begin with a full-repository audit unless explicitly requested.
- Do not recursively inspect unrelated directories or investigate nearby unrelated features.
- Do not start another milestone after completing the requested one.

### 2. Repository-reading discipline

- Do not unnecessarily read the entire repository, full Git history, historical commits, unrelated
  adapters, tests, migrations, GitHub Actions workflows, large historical documentation, old
  planning documents, generated files, caches, or build artifacts.
- Do not read `docs/task_log.md` in full unless directly required.
- When a symbol, function, or file is known, inspect it directly instead of repeatedly searching the
  whole repository.
- Do not reread established file contents during the same session unless they changed or new
  evidence requires it.

### 3. Search before broad reading

- Search for the relevant class, function, route, model, or field first.
- Inspect direct callers and dependencies, following the execution path only as far as necessary.
- Avoid opening large files unrelated to that execution path.
- Prefer `targeted search -> relevant file -> direct dependency/caller -> implementation` over
  repository-wide reading.

### 4. Smallest-correct-change rule

- Implement the smallest correct change consistent with the existing architecture.
- Do not refactor unrelated code, rename unrelated symbols, reorganize directories, introduce
  abstractions without need, rewrite working components, perform opportunistic cleanup, change
  unrelated formatting, or broaden the task because another improvement was noticed.
- Report an unrelated issue as a remaining limitation or follow-up instead of implementing it.

### 5. Preserve existing architecture

- Before adding a model, table, migration, service, repository, abstraction, framework, dependency,
  or workflow, determine whether the existing architecture already supports the requirement.
- Reuse existing structures whenever practical.
- Add a database migration only when a persistent schema change is genuinely required.
- Do not redesign architecture to solve a localized defect.

### 6. Documentation discipline

- Do not update documentation automatically for every code change.
- Update it only for material architecture, externally meaningful behavior, operational procedure,
  CLI/API contract, deployment behavior, or permanent engineering-rule changes.
- Do not rewrite large documentation files for a small defect or update historical task logs unless
  explicitly required.
- Keep documentation changes focused on behavior actually changed.

### 7. Testing discipline

- During implementation, run focused tests for the affected subsystem and use the smallest relevant
  selection while iterating. Fix focused failures before broader validation.
- Do not repeatedly run the full test suite after every edit.
- Once implementation is stable, run the complete required validation once. When relevant, the
  default final validation is:

  ```text
  uv run pytest -q
  uv run ruff check .
  uv run alembic current
  uv run alembic check
  git diff --check
  ```

- For documentation-only changes, do not run the full application suite unless explicitly requested
  or required by repository policy.
- Validate the migration chain when a migration is added.
- If final validation fails, fix the failure, rerun only what is necessary, and repeat final
  validation when appropriate.

### 8. Command-output discipline

- Avoid producing or rereading unnecessarily large command output. Prefer quiet modes such as
  `pytest -q` when sufficient.
- For failures, inspect the relevant failure without repeatedly printing complete successful logs.
- Do not dump full database contents, repository trees, generated artifacts, massive diffs, or
  complete test logs unless diagnosis requires it.

### 9. Git discipline

Normally:

1. Inspect targeted files.
2. Implement.
3. Run focused tests.
4. Run final validation once.
5. Self-review the final diff.
6. Commit.
7. Push.
8. Report the commit SHA.
9. Stop.

- Use `git diff` and `git diff --check` appropriately.
- Do not repeatedly inspect Git state without reason, inspect full Git history unless the task
  requires historical reasoning, or create unrelated commits.

### 10. GitHub Actions / CI discipline

- After pushing, do not continuously poll GitHub Actions, wait for CI completion unless explicitly
  requested, or repeatedly query workflow status.
- Report the pushed commit SHA and stop. CI verification can be performed separately by ChatGPT or
  the user.
- If explicitly asked to verify CI, check it efficiently and avoid repeated polling.

### 11. Network discipline

- Do not browse external websites unless the task requires it.
- For source-adapter work, use existing fixtures and tests first when sufficient.
- Do not repeatedly call official government websites during development when deterministic fixtures
  can validate the implementation.
- Never increase source request rates to make development faster. Preserve existing source pacing,
  safety, provenance, and trust constraints.

### 12. Database discipline

- Do not repeatedly recreate or migrate the database unless required.
- Do not create a migration for code-only behavior changes.
- Use focused database checks where sufficient and do not query large tables unnecessarily.
- Preserve immutable recruitment evidence and history.

### 13. Reasoning/time discipline

- Spend deeper investigation only where uncertainty or architectural risk justifies it.
- For a straightforward localized task: inspect, implement, test, and stop.
- Do not continue exploring after acceptance criteria are satisfied or optimize unrelated code in the
  same session.
- Correctness is more important than speed, but unnecessary exploration is not correctness.

### 14. Acceptance-criteria discipline

- Identify the prompt's acceptance criteria before implementation.
- Use them to determine which files to inspect, behavior to change, tests to add, and when the task is
  complete.
- Once all acceptance criteria are satisfied and final validation passes, stop and do not invent
  additional requirements.

### 15. Final-response discipline

- Keep the final Codex response concise, normally approximately 10-20 lines unless the user requests
  detail.
- Report only the root cause, implementation or change, important files changed, migration status
  when relevant, focused/full validation results, commit SHA when committed, and any relevant
  remaining limitation or follow-up.
- Do not include lengthy implementation narration, full logs or diffs, repeated summaries, or an
  explanation of every command.

### 16. Mandatory stop conditions

Stop when the requested behavior is implemented, acceptance tests and required validation pass, and
the requested commit and push are complete.

Do not start the next milestone, fix unrelated discoveries, perform another architecture review,
wait for CI unless explicitly requested, or continue repository exploration after completion.

### 17. Rules that must never be sacrificed for speed

Token and time optimization must never weaken correctness, deterministic behavior, official-source
trust, provenance, evidence preservation, Advertisement-to-Post separation, Human Review safeguards,
immutable Master/history behavior, public/private runtime isolation, security, or test quality for
changed behavior. Efficiency means removing unnecessary work, not skipping necessary engineering
work.
