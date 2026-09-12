import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class StoredRawDocument:
    storage_uri: str
    path: Path
    created: bool


class LocalRawStorage:
    """Content-addressed, provider-neutral development raw-document storage."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def store(
        self,
        *,
        source_code: str,
        content: bytes,
        extension: str,
        observed_at: datetime | None = None,
    ) -> StoredRawDocument:
        observed_at = observed_at or datetime.now(UTC)
        digest = hashlib.sha256(content).hexdigest()
        safe_source = source_code.strip().lower()
        safe_extension = extension.strip().lower().lstrip(".") or "bin"
        relative = (
            Path(safe_source)
            / f"{observed_at:%Y}"
            / f"{observed_at:%m}"
            / (f"{digest}.{safe_extension}")
        )
        path = self.root / relative
        created = not path.exists()
        if created:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
        return StoredRawDocument(
            storage_uri=f"raw://{relative.as_posix()}",
            path=path,
            created=created,
        )
