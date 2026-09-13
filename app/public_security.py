import asyncio
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PUBLIC_CACHE_PATHS = ("/jobs", "/api/public/v1/")
_MAX_RATE_BUCKETS = 10_000
_SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), geolocation=(), microphone=()",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


@dataclass
class _RateBucket:
    started_at: float
    count: int


class PublicRateLimiter:
    """Small-process fixed-window guard for the bounded V0 public surface."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.requests = requests
        self.window_seconds = window_seconds
        self.clock = clock
        self._buckets: dict[str, _RateBucket] = {}
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_public_content_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        client_key = client[0] if client else "unknown"
        now = self.clock()
        async with self._lock:
            if client_key not in self._buckets and len(self._buckets) >= _MAX_RATE_BUCKETS:
                self._buckets = {
                    key: value
                    for key, value in self._buckets.items()
                    if now - value.started_at < self.window_seconds
                }
                if len(self._buckets) >= _MAX_RATE_BUCKETS:
                    client_key = "rate-bucket-overflow"
            bucket = self._buckets.get(client_key)
            if bucket is None or now - bucket.started_at >= self.window_seconds:
                bucket = _RateBucket(started_at=now, count=0)
                self._buckets[client_key] = bucket
            bucket.count += 1
            allowed = bucket.count <= self.requests
            retry_after = max(1, int(self.window_seconds - (now - bucket.started_at)))
        if not allowed:
            await _send_plain_response(
                send,
                429,
                b"Public request limit exceeded",
                [(b"retry-after", str(retry_after).encode("ascii"))],
            )
            return
        await self.app(scope, receive, send)


class PublicResponsePolicy:
    """Apply bounded-request, security-header, and revalidated-cache policy."""

    def __init__(self, app: ASGIApp, *, cache_max_age: int, max_target_bytes: int) -> None:
        self.app = app
        self.cache_max_age = cache_max_age
        self.max_target_bytes = max_target_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        target_size = len(scope.get("raw_path", b"")) + len(scope.get("query_string", b""))
        if target_size > self.max_target_bytes:
            await _send_plain_response(send, 414, b"Request target is too long")
            return
        path = scope.get("path", "")
        if scope.get("method") not in {"GET", "HEAD"} or not _is_public_content_path(path):
            await self._send_with_headers(scope, receive, send)
            return

        captured: list[Message] = []

        async def capture(message: Message) -> None:
            captured.append(message)

        await self.app(scope, receive, capture)
        start = next(
            (message for message in captured if message["type"] == "http.response.start"),
            None,
        )
        if start is None:
            return
        body = b"".join(
            message.get("body", b"")
            for message in captured
            if message["type"] == "http.response.body"
        )
        headers = MutableHeaders(raw=list(start.get("headers", [])))
        _set_security_headers(headers, scope)
        if start["status"] == 200:
            etag = f'"{hashlib.sha256(body).hexdigest()}"'
            headers["etag"] = etag
            headers["cache-control"] = f"public, max-age={self.cache_max_age}, must-revalidate"
            request_headers = Headers(scope=scope)
            if request_headers.get("if-none-match") == etag:
                if "content-length" in headers:
                    del headers["content-length"]
                if "content-type" in headers:
                    del headers["content-type"]
                await send({"type": "http.response.start", "status": 304, "headers": headers.raw})
                await send({"type": "http.response.body", "body": b""})
                return
        else:
            headers["cache-control"] = "no-store"
        start["headers"] = headers.raw
        for message in captured:
            await send(start if message["type"] == "http.response.start" else message)

    async def _send_with_headers(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def add_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=list(message.get("headers", [])))
                _set_security_headers(headers, scope)
                headers["cache-control"] = "no-store"
                message["headers"] = headers.raw
            await send(message)

        await self.app(scope, receive, add_headers)


def _is_public_content_path(path: str) -> bool:
    return path == "/jobs" or path.startswith("/jobs/") or path.startswith(_PUBLIC_CACHE_PATHS[1])


def _set_security_headers(headers: MutableHeaders, scope: Scope) -> None:
    for name, value in _SECURITY_HEADERS.items():
        headers[name] = value
    if scope.get("scheme") == "https":
        headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"


async def _send_plain_response(
    send: Send,
    status: int,
    body: bytes,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    headers = MutableHeaders(
        raw=[
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
            *(extra_headers or []),
        ]
    )
    for name, value in _SECURITY_HEADERS.items():
        headers[name] = value
    headers["cache-control"] = "no-store"
    await send({"type": "http.response.start", "status": status, "headers": headers.raw})
    await send({"type": "http.response.body", "body": body})
