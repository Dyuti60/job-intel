import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Engine

PIPELINE_LOCK_NAMESPACE = "assam-job-intelligence:pipeline"


def pipeline_advisory_lock_key(source: str) -> int:
    """Return a stable signed PostgreSQL bigint lock key for one source."""
    identity = f"{PIPELINE_LOCK_NAMESPACE}:{source.strip().upper()}".encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)


class PipelineAdvisoryLock:
    """Hold a source-scoped PostgreSQL session advisory lock on a dedicated connection."""

    def __init__(self, engine: Engine, source: str) -> None:
        self.engine = engine
        self.source = source.strip().upper()
        self.lock_key = pipeline_advisory_lock_key(self.source)

    @contextmanager
    def acquire(self) -> Iterator[bool]:
        if self.engine.dialect.name != "postgresql":
            # SQLite remains useful for isolated tests; runtime overlap protection requires
            # PostgreSQL and is validated independently.
            yield True
            return

        with self.engine.connect() as connection:
            acquired = bool(
                connection.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": self.lock_key},
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    connection.scalar(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": self.lock_key},
                    )
