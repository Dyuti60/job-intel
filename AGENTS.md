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
