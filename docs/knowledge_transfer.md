# Assam Job Intelligence — Knowledge Transfer and Operations Guide

## 1. What this system does

Assam Job Intelligence turns recruitment information from registered Assam Government sources into
an approved, traceable Recruitment Master.

In everyday language, it works like a controlled newsroom:

1. **Source Registry** says which websites are allowed and which organization owns them.
2. **Discovery** visits only a registered source and saves exactly what it observed.
3. **Extraction** proposes structured recruitment details, but does not call them true.
4. **Evidence** records the exact source passage behind each proposed value.
5. **Verification** independently compares proposed values with persisted evidence.
6. **Confidence** applies a versioned, explainable rule—not an AI opinion.
7. **Human Review** handles important, uncertain, or conflicting information.
8. **Master Publisher** copies only eligible values into immutable Recruitment Master history.
9. **Public API and website** read only the current ACTIVE Master revision.

The most important safety rule is:

> Discovery data is never published directly. A value must pass the Verification, Confidence, and
> any required Human Review boundaries before it can reach Recruitment Master.

The system is currently Assam-only. The implemented live adapter is the narrow APSC Advertisement
12/2026 flow; it is not a general Internet crawler.

## 2. Who uses which part

| Person | What they use | What they can do |
| --- | --- | --- |
| Job seeker | `/jobs` and `/api/public/v1` | Read approved current recruitment information |
| Human reviewer | `/review` on the private local application | Inspect evidence and record an auditable decision |
| Operator | Pipeline, monitoring commands, `/operations` | Run and observe controlled processing |
| Developer | Tests, Alembic, `/docs`, application logs | Develop and diagnose the system |
| Release operator | Protected GitHub workflows and deployment runbook | Build, validate, back up, and release the public service |

The reviewer and operator pages have no authentication in V0. They are private localhost tools and
must never be routed to the public Internet.

## 3. Complete flow in end-user language

### Step 1 — Register the official source

A RecruitingAuthority represents an organization such as APSC. A SourceEndpoint identifies an
approved page or API belonging to that authority and records whether Discovery is allowed.

This prevents arbitrary web searching from becoming the system's source of truth. Official sources
can establish truth; supporting or secondary sources cannot silently override official evidence.

### Step 2 — Discover source material

Discovery creates a DiscoveryRun for an eligible endpoint. Every observed page or document becomes
an immutable SourceDocument version with its URL, SHA-256 content hash, retrieval metadata, and raw
storage reference.

- Same URL and same bytes: `UNCHANGED`; reuse the known version.
- Same URL and different bytes: `CHANGED`; create a new version and keep the old one.
- First observed URL/content: `NEW`.

Raw content is stored outside PostgreSQL. PostgreSQL retains identity, hashes, and provenance.

### Step 3 — Create an untrusted candidate proposal

A RecruitmentCandidate is the stable identity of a possible recruitment within one authority. A
RecruitmentCandidateRevision is an immutable extraction from one exact SourceDocument version.
CandidateFields store typed values such as a date, integer, decimal, boolean, string, JSON, or null.

At this point the values are proposals only. `READY_FOR_VERIFICATION` means “ready to be checked,”
not “verified” or “approved.”

### Step 4 — Attach extraction evidence

Evidence stores a bounded excerpt/context and provider-neutral source locator from one exact
SourceDocument version. A CandidateField may have several evidence records, and one evidence record
may support several fields.

Evidence answers “where did this extracted value come from?” It does not declare the value true.

### Step 5 — Verify independently

The Verification worker uses only persisted fields and evidence; it does not contact APSC. For each
field it records whether evidence `SUPPORTS`, `CONTRADICTS`, or is `CONTEXT_ONLY`. The Verification
domain then produces one immutable result:

- `CONFIRMED`
- `CONFLICT`
- `INSUFFICIENT_EVIDENCE`
- `NOT_APPLICABLE`

Official source class is derived from stored provenance. A client or worker cannot claim that a
secondary source is authoritative.

### Step 6 — Calculate explainable confidence

Confidence V1 starts from the Verification outcome and applies documented source-support and
conflict modifiers. Repeated evidence from one endpoint does not inflate the score. Important field
paths—such as deadlines, age limits, qualifications, domicile, vacancies, and application URLs—are
treated as critical.

The stored component breakdown explains every point added or removed. Confidence is a deterministic
reliability signal, not a statistical probability, eligibility percentage, or approval.

### Step 7 — Route uncertain work to a human

If a field or revision requires review, the system creates one idempotent ReviewCase containing
snapshot ReviewItems. The reviewer may:

- `APPROVE_AS_IS`
- `CORRECT_AND_APPROVE` for a field
- `REJECT`
- `REQUEST_REVERIFICATION`

A correction never overwrites CandidateField history. The original value and corrected value both
remain traceable. Requesting reverification records the request; it does not itself approve or
publish anything.

### Step 8 — Publish eligible values to Master

The Master Publisher has two allowed paths:

- Completed Verification/Confidence says no review is required: publish original verified values.
- Review was required and the resolved case is approved: publish the approved projection, including
  any typed human corrections.

Rejected, cancelled, unresolved, or reverification-requested cases cannot publish. Publishing the
same effective values is idempotent. Changed effective values create a new immutable MasterRevision
and field-level MasterChange history; unchanged reverification reuses the business revision and adds
publication audit provenance.

### Step 9 — Serve approved information

The public API and `/jobs` website read only ACTIVE RecruitmentMaster records and their current
immutable revision. Drafts, evidence bodies, reviewer identities, Verification internals, pipeline
history, and historical non-current Master revisions do not appear in public responses.

If no recruitment has crossed the complete approval boundary, an empty public list is the correct
and safe result.

## 4. Data lineage at a glance

```text
RecruitingAuthority
  -> SourceEndpoint
      -> DiscoveryRun
          -> SourceDocument version + observation history
              -> RecruitmentCandidate
                  -> immutable CandidateRevision
                      -> typed CandidateFields
                          -> extraction Evidence links
                              -> VerificationRun
                                  -> FieldVerification
                                      -> verification Evidence assessments
                                          -> Confidence assessments
                                              -> ReviewCase when required
                                                  -> ReviewItems
                                                      -> ReviewDecisions
                                              -> approved projection
                                                  -> RecruitmentMaster
                                                      -> immutable MasterRevision
                                                          -> MasterFields
                                                          -> MasterChanges
                                                          -> publication events
```

PipelineRun, PipelineStageRun, and OperationalNotificationEvent sit beside this flow. They describe
operational execution and health; they do not become recruitment truth.

## 5. First local setup

### Prerequisites

- Windows with PowerShell
- Git
- Python 3.12 managed by `uv`
- Docker Desktop with Linux containers
- PostgreSQL, normally through the repository Compose service

From the repository root (`D:\ASSAM_JOB_INTEL`):

```powershell
Copy-Item .env.example .env
uv sync
docker compose up -d postgres
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

The expected current migration head before T-021 is `20260912_0011`.

Do not commit `.env`. Development credentials in `.env.example` are local examples, not production
credentials.

## 6. Run the private application in browser/debug mode

Use the full private application only on localhost:

```powershell
$env:AJI_APP_ENV = "development"
$env:AJI_DEBUG = "true"
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open these addresses in a browser:

| Address | Purpose |
| --- | --- |
| `http://127.0.0.1:8000/jobs` | Public-style approved recruitment website |
| `http://127.0.0.1:8000/review` | Private Human Review queue |
| `http://127.0.0.1:8000/operations` | Private pipeline health and recent history |
| `http://127.0.0.1:8000/docs` | Swagger interface for internal and public APIs |
| `http://127.0.0.1:8000/api/v1/health` | Internal health response |
| `http://127.0.0.1:8000/api/public/v1/recruitments` | Approved public JSON list |

Debug mode can expose detailed exception information. Bind it only to `127.0.0.1`, stop it after
diagnosis, and never use this command as the Internet-facing production process.

Stop the foreground server with `Ctrl+C`.

Before replacing it with another application mode, verify that shutdown completed and port 8000 is
not still owned by a reload child:

```powershell
netstat -ano | Select-String ':8000'
```

Do not run `app.main` and `workers.public_server` on the same port at the same time. A lingering
development reload process can otherwise receive requests intended for the public-only process and
produce a misleading route-isolation test.

## 7. Run the safe public-only application

For local production-surface checking, run the bounded application instead of `app.main`:

```powershell
$env:AJI_APP_ENV = "production"
$env:AJI_DEBUG = "false"
$env:AJI_PUBLIC_ALLOWED_HOSTS = "localhost,127.0.0.1"
uv run python -m workers.public_server
```

This application contains only `/jobs`, `/api/public/v1`, `/static`, `/healthz`, and `/readyz`.
`/review`, `/operations`, internal `/api/v1`, `/docs`, and `/openapi.json` are absent.

Run its automated boundary check with:

```powershell
uv run python scripts/public_release_smoke.py --base-url http://127.0.0.1:8000
```

## 8. Normal operator workflow

### Preview the full pipeline without domain changes

```powershell
uv run python -m workers.pipeline --source APSC --dry-run
```

Dry-run does not persist Discovery, Candidate, Verification, Confidence, Review, or Master changes.
It intentionally records PipelineRun operational history.

### Run the complete one-shot pipeline

```powershell
uv run python -m workers.pipeline --source APSC
```

This runs Discovery, Verification/Confidence/Review routing, and Master Publisher in sequence. A
queued ReviewCase is a successful outcome, not a pipeline failure. The orchestrator never makes a
human decision.

Always run the Publisher stage even when Discovery is unchanged: a human may have resolved a case
since the prior pipeline execution.

### Run stages independently for diagnosis

```powershell
uv run python -m workers.discovery --source APSC --dry-run
uv run python -m workers.discovery --source APSC

uv run python -m workers.verification --authority APSC --dry-run
uv run python -m workers.verification --authority APSC

uv run python -m workers.master_publisher --dry-run
uv run python -m workers.master_publisher
```

Optional Verification targeting:

```powershell
uv run python -m workers.verification --authority APSC --candidate-key APSC_ADVT_12_2026
```

Discovery is the only one of these stages that fetches the registered APSC flow. Verification uses
persisted evidence. Publisher uses persisted Confidence and Review outcomes.

### Check operational health

```powershell
uv run python -m workers.monitoring --source APSC --dry-run
uv run python -m workers.monitoring --source APSC
```

Dry-run predicts notifications. Normal monitoring stores deduplicated events and sends only through
configured local channels. Use `/operations` for a readable private view.

## 9. Human Review walkthrough

1. Start the private local application.
2. Open `http://127.0.0.1:8000/review`.
3. Open the highest-priority queued case.
4. Read candidate identity, field value, confidence breakdown, extraction evidence, Verification
   assessments, source URL, and source class.
5. Select **Start Review**. This changes the case from `QUEUED` to `IN_REVIEW`.
6. Decide each routed item using the evidence—not merely the confidence number.
7. Supply the reviewer identifier. Notes are required for correction, rejection, and reverification.
8. For a correction, enter a value of the same type as the original field. The corrected value must
   differ from the original.
9. The final item decision automatically resolves the case and calculates the overall outcome.
10. Inspect the approved-projection preview. It is still not Recruitment Master.
11. Run the Master Publisher or the full pipeline again to publish an eligible resolved result.

Do not approve the real queued APSC case merely to test the interface. Use controlled test data for
decision demonstrations unless an operator has genuinely reviewed the source evidence.

## 10. Decision and publication outcomes

ReviewCase overall precedence is:

1. Any `REQUEST_REVERIFICATION` -> `REVERIFICATION_REQUESTED`
2. Otherwise any `REJECT` -> `REJECTED`
3. Otherwise any correction -> `APPROVED_WITH_CORRECTIONS`
4. Otherwise all accepted -> `APPROVED`

| State | Can Publisher create/update Master? |
| --- | --- |
| Confidence says review is not required | Yes, after completed integrity checks |
| ReviewCase `QUEUED` or `IN_REVIEW` | No |
| ReviewCase `APPROVED` | Yes, using original approved values |
| ReviewCase `APPROVED_WITH_CORRECTIONS` | Yes, using the approved projection |
| ReviewCase `REJECTED` | No |
| ReviewCase `REVERIFICATION_REQUESTED` | No; Verification worker may create one controlled retry |
| ReviewCase `CANCELLED` | No |

## 11. Useful read-only URLs

When `app.main` is running locally:

```text
GET /api/v1/source-authorities
GET /api/v1/source-endpoints
GET /api/v1/discovery-runs
GET /api/v1/source-documents
GET /api/v1/recruitment-candidates
GET /api/v1/evidence
GET /api/v1/verification-runs
GET /api/v1/review-cases
GET /api/v1/recruitment-master
GET /api/v1/pipeline-runs
GET /api/v1/operational-status/APSC
GET /api/v1/operational-notifications
GET /api/public/v1/recruitments
```

Use `/docs` to inspect exact filters and response schemas. Some internal APIs also provide controlled
mutations; use the domain UI/workers for normal operations rather than improvising state changes in
Swagger.

## 12. Debugging checklist

### The application does not start

```powershell
docker compose ps
uv run alembic current
uv run alembic check
uv run python -c "from app.core.config import get_settings; print(get_settings().app_env)"
```

Do not print the database URL in shared logs or screenshots.

### Database connection fails

- Confirm the PostgreSQL container is healthy.
- Confirm `.env` exists and `AJI_DATABASE_URL` points to the intended database.
- Run `uv run alembic upgrade head`.
- Never replace a production credential with the example development password.

### `/jobs` is empty

This normally means no ACTIVE RecruitmentMaster has been published. Check `/review`, then inspect
the Master Publisher dry-run. Do not fall back to unverified Candidate data to populate the page.

### Verification confirms fewer fields than expected

This is safe conservative behavior. Inspect persisted Evidence and FieldVerification. Missing or
ambiguous evidence should remain `INSUFFICIENT_EVIDENCE`, not be force-confirmed.

### Pipeline reports overlap

Another execution holds the source-scoped PostgreSQL advisory lock. Let that execution finish. Do
not remove the overlap guard or run stages concurrently against the same source.

### A pipeline or stage failed

Use `/operations` or `GET /api/v1/pipeline-runs/{id}`. Error summaries are intentionally bounded and
redacted; consult local application logs for deeper diagnosis without copying secrets.

### Browser returns 404 for private routes in public mode

That is expected. Stop the public-only process and start `app.main` on localhost for private
administration. Never add private routes to `app.public_main`.

## 13. Tests and developer validation

Before handing over a change:

```powershell
uv sync --frozen
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run pytest -q
uv run ruff check .
git diff --check
```

Schema changes require a new Alembic migration; never edit an approved earlier migration. Tests use
fixtures/mocks and must not depend on live Assam websites.

GitHub CI repeats the full migration chain, tests, Ruff, and public-container build using an isolated
PostgreSQL service. It never runs live APSC Discovery.

## 14. Scheduled operation

The trusted `scheduled-pipeline.yml` workflow uses the registered self-hosted Windows x64 runner.
It runs daily at 08:00 IST and supports manual dispatch. GitHub concurrency plus the database
advisory lock prevents overlap. Persistent runtime configuration and raw data remain under
`D:\ASSAM_JOB_DATA`, outside the Actions checkout.

Human Review-required results stay queued. The workflow never exposes `/review` and never makes a
review decision.

## 15. Public release, backup, and recovery

T-020 uses three workflows:

- **Public Release**: build, vulnerability scan, GHCR push, provenance attestation, optional
  protected deployment by immutable digest.
- **Public Availability**: bounded external health/public/private-route checks every 30 minutes once
  `PUBLIC_BASE_URL` is configured.
- **Restore Rehearsal**: manually restore a selected coordinated backup into a temporary database,
  validate it, and remove it.

Production deployment requires the protected `public-production` Environment, maintainer approval,
DNS, a public hostname, and least-privilege database secrets. Never put those values in source
control. Caddy is the only Internet-facing container and must route only the explicit public paths.

See [Public deployment and recovery](public_deployment.md) and
[Trusted Windows pipeline runner](self_hosted_runner.md) for the detailed operational runbooks.

## 16. Current implementation map

| Milestone | Capability |
| --- | --- |
| T-001 | Foundation and PostgreSQL/Alembic baseline |
| T-002 | Assam Source Registry |
| T-003 | Discovery runs and immutable SourceDocument provenance |
| T-004 | Candidate revisions and typed fields |
| T-005 | Extraction Evidence |
| T-006 | Independent Verification |
| T-007 | Explainable Confidence and review routing |
| T-008 | Human Review domain and approved projection |
| T-009 | Local Human Review web interface |
| T-010/T-010B | Recruitment Master and executable Publisher |
| T-011 | First live APSC adapter |
| T-012 | Automated deterministic Verification worker |
| T-013 | One-shot end-to-end pipeline orchestrator |
| T-014 | Pipeline history and GitHub CI |
| T-015 | Trusted scheduled pipeline execution |
| T-016 | Operational monitoring and notification deduplication |
| T-017 | Public read API |
| T-018 | Public recruitment website |
| T-019 | Public runtime hardening |
| T-020 | Controlled public release automation and recovery rehearsal |

## 17. Handover safety rules

- Keep the project Assam Government recruitment-only.
- Keep official sources authoritative.
- Never publish directly from Discovery or Candidate data.
- Never silently overwrite immutable SourceDocument, Candidate, Verification, Review, or Master
  history.
- Never treat confidence as approval.
- Never bypass required Human Review.
- Never expose `app.main`, `/review`, `/operations`, raw content, or internal APIs publicly.
- Never commit secrets or place persistent runtime data inside an Actions checkout.
- Prefer deterministic code and preserve idempotency at every stage.

## 18. Quick command reference

```powershell
# Start dependencies and migrate
docker compose up -d postgres
uv sync
uv run alembic upgrade head

# Private browser/debug application
$env:AJI_DEBUG = "true"
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Full safe preview / real run
uv run python -m workers.pipeline --source APSC --dry-run
uv run python -m workers.pipeline --source APSC

# Monitoring
uv run python -m workers.monitoring --source APSC --dry-run
uv run python -m workers.monitoring --source APSC

# Publisher only
uv run python -m workers.master_publisher --dry-run
uv run python -m workers.master_publisher

# Quality gates
uv run pytest -q
uv run ruff check .
uv run alembic current
uv run alembic check
git diff --check
```

The next planned implementation is T-021, deterministic eligibility rules and matching over
approved current Master data. Eligibility work must remain downstream of Master and must never
convert missing or ambiguous information into an eligible result.
