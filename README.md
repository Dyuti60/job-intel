# Assam Job Intelligence

Foundation for a trustworthy master-data platform for Assam Government recruitment and job
information. The current implementation includes source, discovery provenance, candidate,
evidence, verification, confidence, and local Human Review capabilities.

## Local setup

1. Copy `.env.example` to `.env` and adjust local values if needed.
2. Run `uv sync`.
3. Run `docker compose up -d postgres`.
4. Run `uv run alembic upgrade head`.
5. Run `uv run uvicorn app.main:app --reload`.

The health endpoint is available at `GET /api/v1/health`.

## Local Human Review UI

Start the application after applying migrations:

```text
uv run uvicorn app.main:app --reload
```

Open `http://localhost:8000/review`. The server-rendered interface shows queued and in-progress
ReviewCases and reuses the existing T-008 lifecycle and decision services. It is intended only for
trusted localhost development. It has no authentication or CSRF protection and must not be exposed
to an untrusted network.
