import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import truststore

USER_AGENT = "AssamJobIntelligence/0.1 (+local development; respectful source discovery)"


class SourceFetchError(RuntimeError):
    pass


class ResponseTooLargeError(SourceFetchError):
    pass


class InvalidContentTypeError(SourceFetchError):
    pass


@dataclass(frozen=True)
class FetchedResource:
    url: str
    content: bytes
    status_code: int
    content_type: str | None
    etag: str | None
    last_modified: str | None
    retrieved_at: datetime


class BoundedHttpClient:
    def __init__(
        self,
        *,
        connect_timeout: float,
        read_timeout: float,
        retries: int,
        max_response_bytes: int,
        requests_per_minute: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.retries = retries
        self.max_response_bytes = max_response_bytes
        self.minimum_request_interval = (
            60.0 / requests_per_minute if requests_per_minute else 0.0
        )
        self.last_request_started: float | None = None
        self.client = httpx.Client(
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=read_timeout,
                pool=connect_timeout,
            ),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "BoundedHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(self, url: str, *, accepted_types: tuple[str, ...]) -> FetchedResource:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self._pace()
                with self.client.stream("GET", url) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "transient source response",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    content_type = response.headers.get("content-type")
                    media_type = (content_type or "").split(";", 1)[0].strip().lower()
                    if accepted_types and media_type not in accepted_types:
                        raise InvalidContentTypeError(
                            f"Unexpected content type {content_type!r} for {url}"
                        )
                    declared = response.headers.get("content-length")
                    if declared and int(declared) > self.max_response_bytes:
                        raise ResponseTooLargeError(f"Response exceeds size limit for {url}")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self.max_response_bytes:
                            raise ResponseTooLargeError(f"Response exceeds size limit for {url}")
                        chunks.append(chunk)
                    return FetchedResource(
                        url=str(response.url),
                        content=b"".join(chunks),
                        status_code=response.status_code,
                        content_type=content_type,
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        retrieved_at=datetime.now(UTC),
                    )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                last_error = error
                status = (
                    error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
                )
                retryable = status is None or status == 429 or status >= 500
                if not retryable or attempt == self.retries:
                    break
                time.sleep(0.1 * (2**attempt))
            except (InvalidContentTypeError, ResponseTooLargeError):
                raise
        raise SourceFetchError(f"Unable to fetch {url}: {last_error}") from last_error

    def _pace(self) -> None:
        now = time.monotonic()
        if self.last_request_started is not None:
            remaining = self.minimum_request_interval - (now - self.last_request_started)
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        self.last_request_started = now
