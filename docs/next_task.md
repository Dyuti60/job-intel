# T-010 — Approved Recruitment Master and Publisher

## Objective

Introduce the canonical cleansed Recruitment Master produced only from eligible reviewed or
verified candidate revisions.

## Scope

T-010 should establish RecruitmentMaster identity, MasterField or equivalent structured approved
values, a deterministic publisher consuming the approved projection, publishing without mutating
candidate/review history, idempotent upsert, master revision/version history, MasterChange audit
records, original-versus-corrected value provenance, source/verification/review provenance,
publication timestamps, and last-verified timestamps.

A revision must not publish when its Review outcome is REJECTED, its Review outcome requests
reverification, required review is unresolved, or confidence/review integrity fails.

## Boundaries

T-010 must not implement live crawling or the public user search UI.
