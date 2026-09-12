from fastapi import APIRouter

from app.api.v1.routes.candidates import router as candidates_router
from app.api.v1.routes.confidence import router as confidence_router
from app.api.v1.routes.discovery import router as discovery_router
from app.api.v1.routes.evidence import router as evidence_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.review import router as review_router
from app.api.v1.routes.source_registry import router as source_registry_router
from app.api.v1.routes.verification import router as verification_router

api_router = APIRouter()
api_router.include_router(candidates_router)
api_router.include_router(confidence_router)
api_router.include_router(discovery_router)
api_router.include_router(evidence_router)
api_router.include_router(health_router)
api_router.include_router(review_router)
api_router.include_router(source_registry_router)
api_router.include_router(verification_router)
