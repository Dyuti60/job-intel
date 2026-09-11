# Architecture

## Purpose and boundaries

Assam Job Intelligence is a trustworthy master-data platform for Assam Government recruitment
information. It turns official source material into evidence-backed, reviewed, approved records.
Eligibility search, user profiles, tracking, alerts, SEO, exam preparation, payments, and national
recruitment are downstream or out of scope.

Official government and recruiting-authority sources are authoritative. Secondary sources can aid
discovery and cross-checking but cannot displace official evidence.

## Conceptual pipeline

```text
Source Registry
  -> Discovery Run
  -> Source Document
  -> Recruitment Candidate
  -> Evidence
  -> Verification
  -> Human Review
  -> Approval
  -> Master Publisher
  -> Recruitment Master
```

The pipeline has a deliberate trust boundary:

- **Raw/discovery data:** registry observations, runs, fetched documents, extracted candidates,
  claims, evidence, and verification results. It preserves what was observed and how it was derived.
- **Cleansed/approved master data:** only approved and publishable recruitment information. Master
  changes retain prior values and an audit trail.

Discovery is never a direct Job Master writer.

## Components and responsibilities

- **Source Registry (implemented in T-002):** persistent inventory of Assam recruiting authorities
  and their explicitly registered endpoints. It records endpoint purpose, authority classification,
  operational state, whether discovery is permitted, optional adapter selection, last verification
  time, and registry provenance. Official, supporting-government, and secondary/discovery-only
  sources are distinguished explicitly. Registry provenance describes why an endpoint is trusted
  or retained; it is not recruitment Evidence.
- **Discovery:** independently replaceable adapters inspect registered sources, record runs, retain
  source documents, detect changes, and propose recruitment candidates. Repeat runs are idempotent.
- **Verification:** independently evaluates candidate field claims against evidence, applying
  deterministic rules wherever possible and producing explainable outcomes.
- **Human Review:** resolves conflicts and handles missing, stale, low-confidence, or critical facts.
  Corrections and decisions are attributable and auditable.
- **Approval:** marks a verified/reviewed revision as publishable. Approval is an explicit boundary,
  not a side effect of discovery.
- **Master Publisher:** idempotently applies approved revisions; it cannot silently overwrite master
  data and must create change history.
- **PostgreSQL Job Master:** authoritative current view of approved Assam recruitment data.
- **Audit/change history:** immutable or append-oriented trace of source observations, decisions,
  approvals, publication events, and old/new master values.
- **Future consumers:** eligibility search, public job search, user profiles, tracking, SEO, alerts,
  and ASSAM_EXAM_AI consume the master but do not own its truth lifecycle.

## Domain layers

The API layer handles transport and schemas. Services coordinate use cases and state transitions.
Domain-oriented packages hold future discovery, verification, review, and publishing behavior.
Repositories isolate persistence. SQLAlchemy models map persistent state. Source adapters isolate
external site behavior. Configuration, logging, and database setup remain infrastructure concerns.

External AI, if later justified, remains an optional provider behind an interface. Crawling, hashing,
deduplication, dates, state transitions, and publication safeguards remain deterministic.

## Implemented Source Registry

`RecruitingAuthority` owns one or more `SourceEndpoint` records. Stable, unique authority codes
support future configuration and adapter selection. Canonical endpoint URLs are normalized
conservatively and globally unique. Enum-backed database checks constrain authority type/status and
endpoint type/class/status. Foreign keys use restricted deletion because deactivation is the normal
operational lifecycle and registered provenance must not disappear casually.

The registry sits before Discovery as an allow-list and trust-classification boundary. Future
Discovery workers may enumerate only registered endpoints that satisfy explicit eligibility policy,
including active authority and endpoint state plus `discovery_enabled=true`. Registration does not
fetch a URL, assert a recruitment fact, create Evidence, or permit direct Job Master writes.
