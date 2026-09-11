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

