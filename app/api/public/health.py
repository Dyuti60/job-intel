from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["public-health"])
DatabaseSession = Annotated[Session, Depends(get_db)]


class PublicHealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]


@router.get("/healthz", response_model=PublicHealthResponse, include_in_schema=False)
def public_liveness() -> PublicHealthResponse:
    return PublicHealthResponse(status="ok")


@router.get("/readyz", response_model=PublicHealthResponse, include_in_schema=False)
def public_readiness(
    response: Response,
    session: DatabaseSession,
) -> PublicHealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return PublicHealthResponse(status="unavailable")
    return PublicHealthResponse(status="ok")
