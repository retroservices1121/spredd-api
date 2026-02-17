from pydantic import BaseModel


class QuoteRequest(BaseModel):
    platform: str
    market_id: str
    outcome: str  # "yes" or "no"
    side: str  # "buy" or "sell"
    amount: float


class QuoteResponse(BaseModel):
    platform: str
    market_id: str
    outcome: str
    side: str
    input_amount: float
    expected_output: float
    price_per_token: float
    price_impact: float | None = None
    fee_amount: float
    fee_bps: int = 50
    expires_at: str | None = None
    quote_data: dict | None = None  # Opaque data needed for prepare/execute


class PrepareRequest(BaseModel):
    platform: str
    market_id: str
    outcome: str
    side: str
    amount: float
    wallet_address: str


class TransactionData(BaseModel):
    to: str
    data: str
    value: str
    gas: str | None = None
    chain_id: int
    description: str


class PrepareResponse(BaseModel):
    transactions: list[TransactionData]
    quote: QuoteResponse


class ExecuteRequest(BaseModel):
    platform: str
    market_id: str
    outcome: str
    side: str
    amount: float
    wallet_address: str
    private_key: str  # Used in-memory only, never stored


class ExecuteResponse(BaseModel):
    tx_hash: str
    status: str
    platform: str
    market_id: str
    input_amount: float
    output_amount: float | None = None
    fee_amount: float
    explorer_url: str | None = None
