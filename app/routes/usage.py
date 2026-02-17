from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.db.models import APIKey
from app.dependencies import get_current_api_key
from app.services.usage_tracker import get_current_usage

router = APIRouter()


@router.get("/usage")
async def get_usage(
    api_key: APIKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get current billing period usage: requests, trades, volume, fees."""
    usage = await get_current_usage(db, api_key.account_id)
    return {
        "account_id": str(api_key.account_id),
        "api_key_prefix": api_key.key_prefix,
        "tier": api_key.tier.value,
        "rate_limit_rpm": api_key.rate_limit_rpm,
        "rate_limit_tpm": api_key.rate_limit_tpm,
        **usage,
    }
