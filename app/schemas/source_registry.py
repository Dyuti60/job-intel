import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    UrlConstraints,
    field_validator,
    model_validator,
)

from app.models.source_registry import (
    AuthorityStatus,
    AuthorityType,
    SourceClass,
    SourceStatus,
    SourceType,
)
from app.services.url_normalization import normalize_http_url

RegistryHttpUrl = Annotated[
    HttpUrl,
    UrlConstraints(max_length=2048),
    AfterValidator(lambda value: HttpUrl(normalize_http_url(value))),
]


class RegistrySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RecruitingAuthorityCreate(RegistrySchema):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=1, max_length=255)
    authority_type: AuthorityType
    official_website_url: RegistryHttpUrl
    status: AuthorityStatus = AuthorityStatus.ACTIVE

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("name must not be blank")
        return normalized

class RecruitingAuthorityRead(RegistrySchema):
    id: uuid.UUID
    code: str
    name: str
    authority_type: AuthorityType
    official_website_url: RegistryHttpUrl
    status: AuthorityStatus
    created_at: datetime
    updated_at: datetime


class RecruitingAuthorityUpdate(RegistrySchema):
    status: AuthorityStatus


class SourceEndpointCreate(RegistrySchema):
    recruiting_authority_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    canonical_url: RegistryHttpUrl
    source_type: SourceType
    source_class: SourceClass
    status: SourceStatus = SourceStatus.ACTIVE
    discovery_enabled: bool = True
    adapter_key: str | None = Field(default=None, min_length=1, max_length=128)
    last_verified_at: datetime | None = None
    provenance_note: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("adapter_key", "provenance_note")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("last_verified_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("last_verified_at must include a timezone")
        return value


class SourceEndpointUpdate(RegistrySchema):
    status: SourceStatus | None = None
    discovery_enabled: bool | None = None
    adapter_key: str | None = Field(default=None, min_length=1, max_length=128)
    last_verified_at: datetime | None = None
    provenance_note: str | None = Field(default=None, max_length=2000)

    @field_validator("adapter_key", "provenance_note")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("last_verified_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("last_verified_at must include a timezone")
        return value

    @model_validator(mode="after")
    def reject_null_operational_fields(self) -> "SourceEndpointUpdate":
        for field_name in ("status", "discovery_enabled"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class SourceEndpointRead(RegistrySchema):
    id: uuid.UUID
    recruiting_authority_id: uuid.UUID
    name: str
    canonical_url: RegistryHttpUrl
    source_type: SourceType
    source_class: SourceClass
    status: SourceStatus
    discovery_enabled: bool
    adapter_key: str | None
    last_verified_at: datetime | None
    provenance_note: str | None
    created_at: datetime
    updated_at: datetime
