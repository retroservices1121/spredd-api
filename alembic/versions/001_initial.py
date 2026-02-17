"""Initial schema — 6 tables

Revision ID: 001
Revises:
Create Date: 2025-01-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # accounts
    op.create_table(
        "accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("company_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean, default=True),
    )

    # api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(255)),
        sa.Column("tier", sa.String(20), default="free"),
        sa.Column("rate_limit_rpm", sa.Integer, default=60),
        sa.Column("rate_limit_tpm", sa.Integer, default=5),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )

    # api_usage
    op.create_table(
        "api_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("api_key_id", UUID(as_uuid=True), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("response_time_ms", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # trades
    op.create_table(
        "trades",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("api_key_id", UUID(as_uuid=True), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("wallet_address", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("chain", sa.String(50), nullable=False),
        sa.Column("market_id", sa.String(255), nullable=False),
        sa.Column("market_title", sa.Text),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("input_amount", sa.String(50), nullable=False),
        sa.Column("output_amount", sa.String(50)),
        sa.Column("price", sa.Numeric(20, 10)),
        sa.Column("fee_amount", sa.String(50)),
        sa.Column("tx_hash", sa.String(255)),
        sa.Column("status", sa.String(20), default="quoted"),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # positions
    op.create_table(
        "positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("api_key_id", UUID(as_uuid=True), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("wallet_address", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("market_id", sa.String(255), nullable=False),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("token_amount", sa.String(50), nullable=False),
        sa.Column("avg_entry_price", sa.Numeric(20, 10), nullable=False),
        sa.Column("current_price", sa.Numeric(20, 10)),
        sa.Column("status", sa.String(20), default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("api_key_id", "wallet_address", "platform", "market_id", "outcome"),
    )

    # billing_periods
    op.create_table(
        "billing_periods",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_requests", sa.Integer, default=0),
        sa.Column("total_trades", sa.Integer, default=0),
        sa.Column("total_volume", sa.String(50), default="0"),
        sa.Column("total_fees", sa.String(50), default="0"),
    )


def downgrade() -> None:
    op.drop_table("billing_periods")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("api_usage")
    op.drop_table("api_keys")
    op.drop_table("accounts")
