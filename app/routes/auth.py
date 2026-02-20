import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import generate_api_key
from app.db.engine import get_db
from app.db.models import TIER_LIMITS, Account, APIKey, Tier
from app.schemas.auth import (
    APIKeyCreatedResponse,
    APIKeyListItem,
    CreateAPIKeyRequest,
    SignupRequest,
    SignupResponse,
)

router = APIRouter()


@router.post("/signup", response_model=SignupResponse)
async def signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Account).where(Account.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    account = Account(email=req.email, company_name=req.company_name)
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return SignupResponse(account_id=account.id, email=account.email, created_at=account.created_at)


@router.post("/api-keys", response_model=APIKeyCreatedResponse)
async def create_api_key(req: CreateAPIKeyRequest, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, req.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    try:
        tier = Tier(req.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {req.tier}. Must be free, builder, pro, or feed")

    limits = TIER_LIMITS[tier]
    full_key, prefix, key_hash = generate_api_key()

    api_key = APIKey(
        account_id=account.id,
        key_prefix=prefix,
        key_hash=key_hash,
        label=req.label,
        tier=tier,
        rate_limit_rpm=limits["rpm"],
        rate_limit_tpm=limits["tpm"],
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreatedResponse(
        id=api_key.id,
        api_key=full_key,
        key_prefix=prefix,
        label=api_key.label,
        tier=api_key.tier.value,
        rate_limit_rpm=api_key.rate_limit_rpm,
        rate_limit_tpm=api_key.rate_limit_tpm,
        created_at=api_key.created_at,
    )


@router.get("/api-keys", response_model=list[APIKeyListItem])
async def list_api_keys(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(APIKey).where(APIKey.account_id == account_id).order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        APIKeyListItem(
            id=k.id,
            key_prefix=k.key_prefix,
            label=k.label,
            tier=k.tier.value,
            is_active=k.is_active,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    api_key = await db.get(APIKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    api_key.is_active = False
    await db.commit()
    return {"status": "revoked"}
