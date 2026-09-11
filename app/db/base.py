from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative metadata for all future database models."""

