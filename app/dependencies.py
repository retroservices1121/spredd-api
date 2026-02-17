from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_keys import hash_api_key
from app.auth.rate_limiter import rate_limiter_store
from app.db.engine import get_db
from app.db.models import APIKey


async def get_current_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    key_hash = hash_api_key(x_api_key)
    result = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True)))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return api_key


def require_request_limit(api_key: APIKey = Depends(get_current_api_key)) -> APIKey:
    bucket = rate_limiter_store.check_request_limit(str(api_key.id), api_key.rate_limit_rpm)
    if not bucket.consume():
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(api_key.rate_limit_rpm),
                "X-RateLimit-Remaining": str(bucket.remaining),
                "X-RateLimit-Reset": str(int(bucket.reset_in)),
            },
        )
    return api_key


def require_trade_limit(api_key: APIKey = Depends(get_current_api_key)) -> APIKey:
    # Check both request limit and trade limit
    req_bucket = rate_limiter_store.check_request_limit(str(api_key.id), api_key.rate_limit_rpm)
    if not req_bucket.consume():
        raise HTTPException(
            status_code=429,
            detail="Request rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(api_key.rate_limit_rpm),
                "X-RateLimit-Remaining": str(req_bucket.remaining),
                "X-RateLimit-Reset": str(int(req_bucket.reset_in)),
            },
        )
    trade_bucket = rate_limiter_store.check_trade_limit(str(api_key.id), api_key.rate_limit_tpm)
    if not trade_bucket.consume():
        raise HTTPException(
            status_code=429,
            detail="Trade rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(api_key.rate_limit_tpm),
                "X-RateLimit-Remaining": str(trade_bucket.remaining),
                "X-RateLimit-Reset": str(int(trade_bucket.reset_in)),
            },
        )
    return api_key
