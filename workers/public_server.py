import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.public_main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips=settings.public_forwarded_allow_ips,
        server_header=False,
    )


if __name__ == "__main__":
    main()
