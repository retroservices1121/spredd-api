import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    company_name: str | None = None


class SignupResponse(BaseModel):
    account_id: uuid.UUID
    email: str
    created_at: datetime


class CreateAPIKeyRequest(BaseModel):
    account_id: uuid.UUID
    label: str | None = None
    tier: str = "free"


class APIKeyResponse(BaseModel):
    id: uuid.UUID
    key_prefix: str
    label: str | None
    tier: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    created_at: datetime


class APIKeyCreatedResponse(APIKeyResponse):
    api_key: str  # Full key, shown only once


class APIKeyListItem(BaseModel):
    id: uuid.UUID
    key_prefix: str
    label: str | None
    tier: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
