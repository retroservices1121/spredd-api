"""Fee embedding logic per platform — 0.5% (50 bps) on every trade."""

from decimal import Decimal

FEE_BPS = 50  # 0.5%


def calculate_fee(amount: Decimal) -> Decimal:
    """Calculate the 0.5% platform fee on a trade amount."""
    return amount * Decimal(FEE_BPS) / Decimal(10000)


def get_fee_bps() -> int:
    return FEE_BPS


PLATFORM_FEE_MECHANISMS = {
    "kalshi": {
        "mechanism": "feeAccount + platformFeeScale in order params",
        "description": "Set scale to 25 (= 50 bps)",
    },
    "polymarket": {
        "mechanism": "Builder API key",
        "description": "Fee configured at Polymarket builder dashboard",
    },
    "myriad": {
        "mechanism": "referral_code in quote request",
        "description": "Revenue share configured on Myriad side",
    },
    "opinion": {
        "mechanism": "Post-trade transfer",
        "description": "Auto-transfer 0.5% after trade in execute mode; fee tx in prepare mode",
    },
    "limitless": {
        "mechanism": "Post-trade transfer",
        "description": "Auto-transfer 0.5% after trade in execute mode; fee tx in prepare mode",
    },
}
