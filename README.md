# Assam Job Intelligence

Foundation for a trustworthy master-data platform for Assam Government recruitment and job
information. The current implementation is T-001: project and architecture baseline only.

## Local setup

1. Copy `.env.example` to `.env` and adjust local values if needed.
2. Run `uv sync`.
3. Run `docker compose up -d postgres`.
4. Run `uv run alembic upgrade head`.
5. Run `uv run uvicorn app.main:app --reload`.

The health endpoint is available at `GET /api/v1/health`.

