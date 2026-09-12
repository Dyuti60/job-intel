from fastapi import APIRouter

from app.api.v1.routes.discovery import router as discovery_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.source_registry import router as source_registry_router

api_router = APIRouter()
api_router.include_router(discovery_router)
api_router.include_router(health_router)
api_router.include_router(source_registry_router)
