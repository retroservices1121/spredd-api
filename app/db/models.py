import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tier(str, enum.Enum):
    FREE = "free"
    BUILDER = "builder"
    PRO = "pro"


TIER_LIMITS = {
    Tier.FREE: {"rpm": 60, "tpm": 5},
    Tier.BUILDER: {"rpm": 300, "tpm": 30},
    Tier.PRO: {"rpm": 1000, "tpm": 100},
}


class TradeStatus(str, enum.Enum):
    QUOTED = "quoted"
    PREPARED = "prepared"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class TradeMode(str, enum.Enum):
    PREPARE = "prepare"
    EXECUTE = "execute"


class PositionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    billing_periods: Mapped[list["BillingPeriod"]] = relationship(back_populates="account")


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(255))
    tier: Mapped[Tier] = mapped_column(Enum(Tier), default=Tier.FREE)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)
    rate_limit_tpm: Mapped[int] = mapped_column(Integer, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped["Account"] = relationship(back_populates="api_keys")


class APIUsage(Base):
    __tablename__ = "api_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    chain: Mapped[str] = mapped_column(String(50), nullable=False)
    market_id: Mapped[str] = mapped_column(String(255), nullable=False)
    market_title: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    input_amount: Mapped[str] = mapped_column(String(50), nullable=False)
    output_amount: Mapped[str | None] = mapped_column(String(50))
    price: Mapped[float | None] = mapped_column(Numeric(20, 10))
    fee_amount: Mapped[str | None] = mapped_column(String(50))
    tx_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[TradeStatus] = mapped_column(Enum(TradeStatus), default=TradeStatus.QUOTED)
    mode: Mapped[TradeMode] = mapped_column(Enum(TradeMode), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("api_key_id", "wallet_address", "platform", "market_id", "outcome"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    market_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    token_amount: Mapped[str] = mapped_column(String(50), nullable=False)
    avg_entry_price: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    current_price: Mapped[float | None] = mapped_column(Numeric(20, 10))
    status: Mapped[PositionStatus] = mapped_column(Enum(PositionStatus), default=PositionStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BillingPeriod(Base):
    __tablename__ = "billing_periods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    total_volume: Mapped[str] = mapped_column(String(50), default="0")
    total_fees: Mapped[str] = mapped_column(String(50), default="0")

    account: Mapped["Account"] = relationship(back_populates="billing_periods")
