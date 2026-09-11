# T-002 — Assam Source Registry

## Objective

Introduce the first persistent domain capability: a registry of authoritative Assam Government and
recruiting-authority sources that future discovery processes can enumerate safely and consistently.

## Scope

T-002 will define and migrate the minimal tables required to store recruiting authorities and their
official source endpoints. It will establish stable identifiers, source type, canonical URL,
authority ownership, active/inactive operational status, timestamps, and basic provenance/audit
fields. It will add typed schemas, repository/service behavior, and versioned API operations needed
to create, read, list, and deliberately update registry entries. Canonical URLs and suitable natural
keys must prevent duplicates, and tests must cover constraints, idempotent registration, validation,
persistence, and API behavior.

T-002 will include an Alembic migration and PostgreSQL-backed validation. It may include a small,
explicit bootstrap mechanism for initial official Assam sources only if the task defines and tests
its provenance and repeatability.

## Boundaries

T-002 will not implement crawling, scheduled discovery, source-document storage, PDF extraction,
recruitment candidates, evidence, verification, confidence scoring, Human Review, approval,
publishing, Recruitment Master, or user-facing product features. Registry records describe where
future discovery may look; they do not themselves assert recruitment facts and cannot write to Job
Master.
