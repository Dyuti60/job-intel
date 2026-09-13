from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.public.health import router as public_health_router
from app.api.public.v1.router import public_api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.public_security import PublicRateLimiter, PublicResponsePolicy
from app.public_web.router import router as public_web_router


@asynccontextmanager
async def public_lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)
    logger.info("public_application_started", extra={"environment": settings.app_env})
    yield
    logger.info("public_application_stopped")


def create_public_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    application = FastAPI(
        title=f"{settings.app_name} Public",
        debug=False,
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=public_lifespan,
    )
    application.include_router(public_health_router)
    application.include_router(public_api_router, prefix="/api/public/v1")
    application.include_router(public_web_router)
    application.mount(
        "/static",
        StaticFiles(directory=Path(__file__).resolve().parent / "static"),
        name="static",
    )
    application.add_middleware(
        PublicRateLimiter,
        requests=settings.public_rate_limit_requests,
        window_seconds=settings.public_rate_limit_window_seconds,
    )
    application.add_middleware(
        PublicResponsePolicy,
        cache_max_age=settings.public_cache_max_age_seconds,
        max_target_bytes=settings.public_max_request_target_bytes,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.public_allowed_host_list,
        www_redirect=False,
    )
    return application


app = create_public_app()
