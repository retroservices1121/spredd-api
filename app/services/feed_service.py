import logging
import time

from app.platforms.base import Market, OrderBook, Outcome
from app.platforms.registry import platform_registry
from app.schemas.feed import (
    FeedOrderBook,
    FeedOrderBookLevel,
    MarketMetadata,
    MarketOdds,
    PlatformHealth,
    ResolutionStatus,
)

logger = logging.getLogger(__name__)

FEED_PLATFORMS = ["polymarket", "kalshi", "limitless", "opinion"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def market_to_odds(m: Market) -> MarketOdds:
    outcomes: dict[str, float] = {}
    if m.yes_price is not None:
        outcomes["yes"] = float(m.yes_price)
    if m.no_price is not None:
        outcomes["no"] = float(m.no_price)
    return MarketOdds(
        market_id=m.market_id,
        platform=m.platform.value,
        title=m.title,
        outcomes=outcomes,
        volume_24h=float(m.volume_24h) if m.volume_24h is not None else None,
        liquidity=float(m.liquidity) if m.liquidity is not None else None,
        last_updated=_now_ms(),
    )


def market_to_metadata(m: Market) -> MarketMetadata:
    raw = m.raw_data or {}
    is_resolved = raw.get("is_resolved", False) or raw.get("resolved", False)
    status = "resolved" if is_resolved else ("active" if m.is_active else "closed")
    resolution_outcome = raw.get("resolution", raw.get("winning_outcome"))

    return MarketMetadata(
        market_id=m.market_id,
        platform=m.platform.value,
        title=m.title,
        description=m.description,
        category=m.category,
        resolution_source=raw.get("resolution_source"),
        end_date=m.close_time,
        created_date=raw.get("created_at", raw.get("created_date")),
        status=status,
        resolution_outcome=str(resolution_outcome) if resolution_outcome else None,
        volume_total=float(m.volume_24h) if m.volume_24h is not None else None,
    )


def market_to_resolution(m: Market) -> ResolutionStatus:
    raw = m.raw_data or {}
    is_resolved = raw.get("is_resolved", False) or raw.get("resolved", False)
    winning = raw.get("resolution", raw.get("winning_outcome"))
    ts = raw.get("resolution_timestamp", raw.get("resolved_at"))
    resolution_ts = None
    if ts is not None:
        try:
            resolution_ts = int(ts)
        except (ValueError, TypeError):
            pass

    return ResolutionStatus(
        market_id=m.market_id,
        platform=m.platform.value,
        is_resolved=bool(is_resolved),
        winning_outcome=str(winning) if winning else None,
        resolution_timestamp=resolution_ts,
    )


def orderbook_to_feed(ob: OrderBook, platform: str) -> FeedOrderBook:
    return FeedOrderBook(
        market_id=ob.market_id,
        platform=platform,
        outcome=ob.outcome.value,
        bids=[FeedOrderBookLevel(price=float(p), quantity=float(q)) for p, q in ob.bids],
        asks=[FeedOrderBookLevel(price=float(p), quantity=float(q)) for p, q in ob.asks],
        last_updated=_now_ms(),
    )


async def sync_all_markets() -> list[MarketOdds]:
    results: list[MarketOdds] = []
    for slug in FEED_PLATFORMS:
        adapter = platform_registry.get(slug)
        if adapter is None:
            continue
        try:
            markets = await adapter.get_markets(limit=2000, active_only=True)
            for m in markets:
                results.append(market_to_odds(m))
        except Exception as e:
            logger.warning(f"Feed sync failed for {slug}: {e}")
    return results


async def get_platform_status() -> list[PlatformHealth]:
    statuses: list[PlatformHealth] = []
    now = _now_ms()
    for slug in FEED_PLATFORMS:
        adapter = platform_registry.get(slug)
        if adapter is None:
            statuses.append(PlatformHealth(platform=slug, is_healthy=False, last_check=now, market_count=0))
            continue
        try:
            markets = await adapter.get_markets(limit=1, active_only=True)
            statuses.append(
                PlatformHealth(platform=slug, is_healthy=True, last_check=now, market_count=len(markets))
            )
        except Exception:
            statuses.append(PlatformHealth(platform=slug, is_healthy=False, last_check=now, market_count=0))
    return statuses
