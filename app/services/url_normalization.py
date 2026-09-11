from urllib.parse import urlsplit, urlunsplit

from pydantic import HttpUrl


def normalize_http_url(value: HttpUrl | str) -> str:
    """Normalize only identity-neutral HTTP URL variations."""
    parsed = urlsplit(str(value).strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()

    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not permitted")

    port = parsed.port
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))
