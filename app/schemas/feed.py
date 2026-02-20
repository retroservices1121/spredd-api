from typing import Any, Optional

from pydantic import BaseModel, Field


class MarketOdds(BaseModel):
    market_id: str
    platform: str
    title: str
    outcomes: dict[str, float] = Field(description="Outcome name -> probability (0-1)")
    volume_24h: Optional[float] = None
    liquidity: Optional[float] = None
    last_updated: int = Field(description="Epoch milliseconds")


class FeedOrderBookLevel(BaseModel):
    price: float
    quantity: float


class FeedOrderBook(BaseModel):
    market_id: str
    platform: str
    outcome: str
    bids: list[FeedOrderBookLevel]
    asks: list[FeedOrderBookLevel]
    last_updated: int = Field(description="Epoch milliseconds")


class MarketMetadata(BaseModel):
    market_id: str
    platform: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    resolution_source: Optional[str] = None
    end_date: Optional[str] = None
    created_date: Optional[str] = None
    status: str = "active"
    resolution_outcome: Optional[str] = None
    volume_total: Optional[float] = None


class ResolutionStatus(BaseModel):
    market_id: str
    platform: str
    is_resolved: bool = False
    winning_outcome: Optional[str] = None
    resolution_timestamp: Optional[int] = None


class PlatformHealth(BaseModel):
    platform: str
    is_healthy: bool
    last_check: int = Field(description="Epoch milliseconds")
    market_count: int = 0


class FeedResponse(BaseModel):
    data_timestamp: int = Field(description="Epoch milliseconds")
    data: Any


class CanaryMarket(BaseModel):
    market_id: str = "canary-staleness-check"
    platform: str = "canary"
    title: str = "Canary Staleness Check"
    outcomes: dict[str, float] = Field(default_factory=dict)
    expected_price: float = 0.0
    injected_at: int = Field(description="Epoch milliseconds")
