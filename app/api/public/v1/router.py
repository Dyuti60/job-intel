from fastapi import APIRouter

from app.api.public.v1.routes.recruitments import router as recruitments_router

public_api_router = APIRouter()
public_api_router.include_router(recruitments_router)
