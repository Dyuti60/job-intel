import re
import unicodedata
import uuid

from fastapi import Request

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def public_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return _NON_ALPHANUMERIC.sub("-", normalized.lower()).strip("-") or "job"


def assam_job_path(job_id: uuid.UUID | str, display_name: str) -> str:
    return f"/jobs/assam/{job_id}/{public_slug(display_name)}"


def assam_advertisement_path(advertisement_id: uuid.UUID | str, title: str) -> str:
    return f"/jobs/assam/advertisements/{advertisement_id}/{public_slug(title)}"


def canonical_url(request: Request, path: str) -> str:
    configured = getattr(request.app.state, "public_base_url", None)
    base = configured or str(request.base_url).rstrip("/")
    return f"{base.rstrip('/')}{path}"


def path_with_query(path: str, query: str) -> str:
    return f"{path}?{query}" if query else path
