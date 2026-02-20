import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.models import APIKey
from app.dependencies import require_request_limit
from app.platforms.base import Outcome
from app.platforms.registry import platform_registry
from app.schemas.feed import FeedResponse, MarketOdds
from app.services.canary import canary_generator
from app.services.feed_service import (
    FEED_PLATFORMS,
    get_platform_status,
    market_to_metadata,
    market_to_odds,
    market_to_resolution,
    orderbook_to_feed,
    sync_all_markets,
)

router = APIRouter()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _validate_platform(platform: str) -> None:
    if platform not in FEED_PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Platform '{platform}' not found. Valid: {FEED_PLATFORMS}")


@router.get("/markets", response_model=FeedResponse)
async def list_feed_markets(
    platform: Optional[str] = Query(None, description="Filter by platform slug"),
    search: Optional[str] = Query(None, description="Search markets by title"),
    category: Optional[str] = Query(None, description="Filter by category"),
    active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    api_key: APIKey = Depends(require_request_limit),
) -> FeedResponse:
    if platform:
        _validate_platform(platform)
        slugs = [platform]
    else:
        slugs = FEED_PLATFORMS

    all_odds: list[MarketOdds] = []
    for slug in slugs:
        adapter = platform_registry.get(slug)
        if adapter is None:
            continue
        try:
            if search:
                markets = await adapter.search_markets(query=search, limit=limit)
            else:
                markets = await adapter.get_markets(
                    limit=limit, offset=offset, active_only=active if active is not None else True
                )
            for m in markets:
                if category and m.category and m.category.lower() != category.lower():
                    continue
                all_odds.append(market_to_odds(m))
        except Exception:
            continue

    # Inject canary
    from app.config import settings

    if settings.feed_canary_enabled:
        canary = canary_generator.current
        all_odds.append(
            MarketOdds(
                market_id=canary.market_id,
                platform=canary.platform,
                title=canary.title,
                outcomes=canary.outcomes,
                volume_24h=None,
                liquidity=None,
                last_updated=canary.injected_at,
            )
        )

    paginated = all_odds[offset : offset + limit] if not search else all_odds[:limit]
    return FeedResponse(data_timestamp=_now_ms(), data=paginated)


@router.get("/markets/{platform}/{market_id}", response_model=FeedResponse)
async def get_feed_market(
    platform: str,
    market_id: str,
    api_key: APIKey = Depends(require_request_limit),
) -> FeedResponse:
    _validate_platform(platform)
    adapter = platform_registry.get(platform)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Platform adapter not available")

    market = await adapter.get_market(market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")

    return FeedResponse(data_timestamp=_now_ms(), data=market_to_odds(market))


@router.get("/markets/{platform}/{market_id}/orderbook", response_model=FeedResponse)
async def get_feed_orderbook(
    platform: str,
    market_id: str,
    outcome: str = Query("yes", description="Outcome: yes or no"),
    api_key: APIKey = Depends(require_request_limit),
) -> FeedResponse:
    _validate_platform(platform)
    adapter = platform_registry.get(platform)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Platform adapter not available")

    try:
        outcome_enum = Outcome(outcome.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid outcome: {outcome}. Must be 'yes' or 'no'")

    ob = await adapter.get_orderbook(market_id, outcome_enum)
    return FeedResponse(data_timestamp=_now_ms(), data=orderbook_to_feed(ob, platform))


@router.get("/markets/{platform}/{market_id}/metadata", response_model=FeedResponse)
async def get_feed_metadata(
    platform: str,
    market_id: str,
    api_key: APIKey = Depends(require_request_limit),
) -> FeedResponse:
    _validate_platform(platform)
    adapter = platform_registry.get(platform)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Platform adapter not available")

    market = await adapter.get_market(market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")

    return FeedResponse(data_timestamp=_now_ms(), data=market_to_metadata(market))


@router.get("/markets/{platform}/{market_id}/resolution", response_model=FeedResponse)
async def get_feed_resolution(
    platform: str,
    market_id: str,
    api_key: APIKey = Depends(require_request_limit),
) -> FeedResponse:
    _validate_platform(platform)
    adapter = platform_registry.get(platform)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Platform adapter not available")

    market = await adapter.get_market(market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")

    return FeedResponse(data_timestamp=_now_ms(), data=market_to_resolution(market))


@router.get("/platforms/status", response_model=FeedResponse)
async def feed_platform_status(
    api_key: APIKey = Depends(require_request_limit),
) -> FeedResponse:
    statuses = await get_platform_status()
    return FeedResponse(data_timestamp=_now_ms(), data=statuses)


@router.get("/sync", response_model=FeedResponse)
async def feed_sync(
    api_key: APIKey = Depends(require_request_limit),
) -> FeedResponse:
    markets = await sync_all_markets()

    from app.config import settings

    if settings.feed_canary_enabled:
        canary = canary_generator.current
        markets.append(
            MarketOdds(
                market_id=canary.market_id,
                platform=canary.platform,
                title=canary.title,
                outcomes=canary.outcomes,
                volume_24h=None,
                liquidity=None,
                last_updated=canary.injected_at,
            )
        )

    return FeedResponse(data_timestamp=_now_ms(), data=markets)
