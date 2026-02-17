"""Usage tracker — log API requests and aggregate billing."""

import uuid
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import APIKey, APIUsage, BillingPeriod, Trade


async def log_request(
    db: AsyncSession,
    api_key_id: uuid.UUID,
    endpoint: str,
    method: str,
    status_code: int,
    response_time_ms: float,
) -> None:
    """Log an API request."""
    usage = APIUsage(
        api_key_id=api_key_id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        response_time_ms=response_time_ms,
    )
    db.add(usage)

    # Update last_used_at
    api_key = await db.get(APIKey, api_key_id)
    if api_key:
        api_key.last_used_at = datetime.now(timezone.utc)

    await db.commit()


async def get_current_usage(db: AsyncSession, account_id: uuid.UUID) -> dict:
    """Get current billing period usage for an account."""
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Get all API keys for this account
    keys_result = await db.execute(select(APIKey.id).where(APIKey.account_id == account_id))
    key_ids = [row[0] for row in keys_result.all()]

    if not key_ids:
        return {
            "period_start": period_start.isoformat(),
            "period_end": (period_start + relativedelta(months=1)).isoformat(),
            "total_requests": 0,
            "total_trades": 0,
            "total_volume": "0",
            "total_fees": "0",
        }

    # Count requests
    req_result = await db.execute(
        select(func.count(APIUsage.id))
        .where(APIUsage.api_key_id.in_(key_ids), APIUsage.created_at >= period_start)
    )
    total_requests = req_result.scalar() or 0

    # Count trades and volume
    trade_result = await db.execute(
        select(func.count(Trade.id), func.coalesce(func.sum(Trade.input_amount), "0"), func.coalesce(func.sum(Trade.fee_amount), "0"))
        .where(Trade.api_key_id.in_(key_ids), Trade.created_at >= period_start)
    )
    row = trade_result.one()
    total_trades = row[0] or 0
    total_volume = str(row[1] or "0")
    total_fees = str(row[2] or "0")

    return {
        "period_start": period_start.isoformat(),
        "period_end": (period_start + relativedelta(months=1)).isoformat(),
        "total_requests": total_requests,
        "total_trades": total_trades,
        "total_volume": total_volume,
        "total_fees": total_fees,
    }
