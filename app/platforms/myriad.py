"""
Myriad Protocol adapter.
Multi-chain prediction market on Abstract, Linea, and BNB Chain.
"""

import logging
import time
from decimal import Decimal
from typing import Any, Optional

import httpx
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3, Web3

from app.config import settings
from app.platforms.base import (
    BasePlatform,
    ChainSlug,
    Market,
    MarketNotFoundError,
    OrderBook,
    Outcome,
    PlatformError,
    PlatformSlug,
    PreparedTransaction,
    Quote,
    TradeResult,
)

logger = logging.getLogger(__name__)

MYRIAD_NETWORKS = {
    2741: {
        "name": "Abstract",
        "chain": ChainSlug.ABSTRACT,
        "rpc": "https://api.mainnet.abs.xyz",
        "prediction_market": "0x3e0F5F8F5Fb043aBFA475C0308417Bf72c463289",
        "collateral": "0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1",  # USDC.e
        "collateral_symbol": "USDC.e",
        "decimals": 6,
    },
    59144: {
        "name": "Linea",
        "chain": ChainSlug.LINEA,
        "rpc": "https://rpc.linea.build",
        "prediction_market": "0x39e66ee6b2ddaf4defded3038e0162180dbef340",
        "collateral": "0x176211869cA2b568f2A7D4EE941E073a821EE1ff",  # USDC
        "collateral_symbol": "USDC",
        "decimals": 6,
    },
    56: {
        "name": "BNB Chain",
        "chain": ChainSlug.BSC,
        "rpc": "https://bsc-dataseed.binance.org",
        "prediction_market": "0x39E66eE6b2ddaf4DEfDEd3038E0162180dbeF340",
        "collateral": "0x55d398326f99059fF775485246999027B3197955",  # USDT
        "collateral_symbol": "USDT",
        "decimals": 18,
    },
}

ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]


class MyriadPlatform(BasePlatform):
    platform = PlatformSlug.MYRIAD
    chain = ChainSlug.ABSTRACT
    name = "Myriad"
    description = "Multi-chain prediction market protocol"
    collateral_symbol = "USDC.e"
    collateral_decimals = 6

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._network_id = settings.myriad_network_id
        self._network = MYRIAD_NETWORKS.get(self._network_id, MYRIAD_NETWORKS[2741])
        self._referral_code = settings.myriad_referral_code
        self._fee_bps = settings.evm_fee_bps
        self._markets_cache: list[Market] = []
        self._markets_cache_time: float = 0
        self._cache_ttl = 300

    async def initialize(self) -> None:
        headers = {"Content-Type": "application/json"}
        if settings.myriad_api_key:
            headers["Authorization"] = f"Bearer {settings.myriad_api_key}"
        self._http = httpx.AsyncClient(
            base_url=settings.myriad_api_url, timeout=30.0, headers=headers,
        )

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        resp = await self._http.request(method, endpoint, **kwargs)
        if resp.status_code == 429:
            raise PlatformError("Rate limit exceeded", "myriad", "429")
        resp.raise_for_status()
        return resp.json()

    def _parse_market(self, data: dict) -> Market:
        prices = data.get("prices", {})
        yes_price = Decimal(str(prices.get("yes", 0))) if prices.get("yes") else None
        no_price = Decimal(str(prices.get("no", 0))) if prices.get("no") else None

        # Fall back to outcomes array
        if yes_price is None:
            outcomes = data.get("outcomes", [])
            if len(outcomes) >= 2:
                yes_price = Decimal(str(outcomes[0].get("price", 0)))
                no_price = Decimal(str(outcomes[1].get("price", 0)))

        network_name = self._network["name"]
        chain = self._network["chain"]

        return Market(
            platform=PlatformSlug.MYRIAD,
            chain=chain,
            market_id=data.get("slug") or str(data.get("id")),
            event_id=data.get("category_slug"),
            title=data.get("title") or data.get("question", ""),
            description=data.get("description"),
            category=data.get("category"),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume", 0))) if data.get("volume") else None,
            liquidity=Decimal(str(data.get("liquidity", 0))) if data.get("liquidity") else None,
            is_active=data.get("status") == "active",
            close_time=data.get("end_date") or data.get("endDate"),
            yes_token=data.get("yes_token_id"),
            no_token=data.get("no_token_id"),
            raw_data=data,
            collateral_token=self._network["collateral_symbol"],
            url=f"https://myriad.markets/{data.get('slug', '')}",
        )

    async def get_markets(self, limit: int = 20, offset: int = 0, active_only: bool = True) -> list[Market]:
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self._cache_ttl:
            return self._markets_cache[offset : offset + limit]

        params = {"limit": 200, "offset": 0, "status": "active" if active_only else "all"}
        params["network_id"] = self._network_id

        data = await self._request("GET", "/markets", params=params)
        markets_data = data if isinstance(data, list) else data.get("markets", data.get("data", []))

        markets = []
        for item in markets_data:
            try:
                markets.append(self._parse_market(item))
            except Exception:
                continue

        self._markets_cache = markets
        self._markets_cache_time = now
        return markets[offset : offset + limit]

    async def search_markets(self, query: str, limit: int = 10) -> list[Market]:
        all_markets = await self.get_markets(limit=200)
        q = query.lower()
        return [m for m in all_markets if q in m.title.lower() or (m.description and q in m.description.lower())][:limit]

    async def get_market(self, market_id: str) -> Optional[Market]:
        for m in self._markets_cache:
            if m.market_id == market_id:
                return m
        try:
            data = await self._request("GET", f"/markets/{market_id}")
            mkt = data if isinstance(data, dict) and "title" in data else data.get("market", data)
            return self._parse_market(mkt)
        except Exception:
            return None

    async def get_orderbook(self, market_id: str, outcome: Outcome) -> OrderBook:
        try:
            data = await self._request("GET", f"/markets/{market_id}/orderbook")
            bids = [(Decimal(str(b["price"])), Decimal(str(b["size"]))) for b in data.get("bids", [])]
            asks = [(Decimal(str(a["price"])), Decimal(str(a["size"]))) for a in data.get("asks", [])]
        except Exception:
            bids, asks = [], []
        return OrderBook(market_id=market_id, outcome=outcome, bids=bids, asks=asks)

    async def get_quote(self, market_id: str, outcome: Outcome, side: str, amount: Decimal) -> Quote:
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", "myriad")

        # Request quote from API
        body = {
            "market_slug": market_id,
            "outcome_id": 0 if outcome == Outcome.YES else 1,
            "action": side,
            "amount": str(amount),
        }
        if self._referral_code:
            body["referral_code"] = self._referral_code

        try:
            data = await self._request("POST", "/markets/quote", json=body)
        except Exception:
            # Fallback to market price
            price = market.yes_price if outcome == Outcome.YES else market.no_price
            price = price or Decimal("0.5")
            expected = amount / price if side == "buy" and price > 0 else amount * price
            data = {"price_average": str(price), "shares": str(expected), "calldata": None, "tx_target": None}

        price_avg = Decimal(str(data.get("price_average", "0.5")))
        shares = Decimal(str(data.get("shares", "0")))
        collateral = self._network["collateral"]

        return Quote(
            platform=PlatformSlug.MYRIAD,
            chain=self._network["chain"],
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=collateral if side == "buy" else "",
            input_amount=amount,
            output_token="" if side == "buy" else collateral,
            expected_output=shares,
            price_per_token=price_avg,
            price_impact=None,
            platform_fee=amount * Decimal(self._fee_bps) / Decimal(10000),
            network_fee_estimate=Decimal("0.001"),
            expires_at=None,
            quote_data={
                "calldata": data.get("calldata"),
                "tx_target": data.get("tx_target"),
                "network_id": self._network_id,
            },
        )

    async def prepare_transaction(
        self, market_id: str, outcome: Outcome, side: str, amount: Decimal, wallet_address: str
    ) -> tuple[list[PreparedTransaction], Quote]:
        quote = await self.get_quote(market_id, outcome, side, amount)
        txs = []
        network = self._network
        collateral = network["collateral"]
        decimals = network["decimals"]
        tx_target = quote.quote_data.get("tx_target") or network["prediction_market"]

        # Approval tx
        amount_raw = int(amount * Decimal(10**decimals))
        w3 = Web3()
        token = w3.eth.contract(address=Web3.to_checksum_address(collateral), abi=ERC20_ABI)
        approve_data = token.encode_abi("approve", args=[Web3.to_checksum_address(tx_target), amount_raw])

        txs.append(PreparedTransaction(
            to=collateral, data=approve_data, value="0",
            gas="100000", chain_id=self._network_id,
            description=f"Approve {network['collateral_symbol']} for Myriad",
        ))

        # Trade tx
        calldata = quote.quote_data.get("calldata") or "0x"
        txs.append(PreparedTransaction(
            to=tx_target, data=calldata, value="0",
            gas="300000", chain_id=self._network_id,
            description=f"{side.upper()} {outcome.value.upper()} on {market_id}",
        ))

        # Fee tx if using post-trade fee collection
        if self._fee_bps > 0 and settings.evm_fee_account:
            fee_amount_raw = int(amount * Decimal(self._fee_bps) / Decimal(10000) * Decimal(10**decimals))
            fee_data = token.encode_abi("approve", args=[Web3.to_checksum_address(settings.evm_fee_account), fee_amount_raw])
            txs.append(PreparedTransaction(
                to=collateral, data=fee_data, value="0",
                gas="60000", chain_id=self._network_id,
                description=f"Platform fee: {self._fee_bps/100}%",
            ))

        return txs, quote

    async def execute_trade(self, quote: Quote, private_key: Any) -> TradeResult:
        if not isinstance(private_key, LocalAccount):
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message="Invalid key type, expected EVM LocalAccount", explorer_url=None,
            )

        try:
            network = self._network
            rpc = network["rpc"]
            if self._network_id == 2741:
                rpc = settings.abstract_rpc_url or rpc
            elif self._network_id == 59144:
                rpc = settings.linea_rpc_url or rpc
            elif self._network_id == 56:
                rpc = settings.bsc_rpc_url or rpc

            w3 = Web3(Web3.HTTPProvider(rpc))
            wallet = private_key.address
            collateral = Web3.to_checksum_address(network["collateral"])
            tx_target = Web3.to_checksum_address(
                quote.quote_data.get("tx_target") or network["prediction_market"]
            )

            # Approve collateral
            token = w3.eth.contract(address=collateral, abi=ERC20_ABI)
            amount_raw = int(quote.input_amount * Decimal(10**network["decimals"]))
            allowance = token.functions.allowance(wallet, tx_target).call()
            if allowance < amount_raw:
                nonce = w3.eth.get_transaction_count(wallet)
                approve_tx = token.functions.approve(tx_target, 2**256 - 1).build_transaction({
                    "from": wallet, "nonce": nonce,
                    "gasPrice": int(w3.eth.gas_price * 1.2),
                    "gas": 100000, "chainId": self._network_id,
                })
                signed = w3.eth.account.sign_transaction(approve_tx, private_key.key)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            # Execute trade
            calldata = quote.quote_data.get("calldata")
            if not calldata:
                raise PlatformError("No calldata in quote", "myriad")

            nonce = w3.eth.get_transaction_count(wallet)
            tx = {
                "from": wallet, "to": tx_target,
                "data": calldata, "value": 0, "nonce": nonce,
                "gasPrice": int(w3.eth.gas_price * 1.2),
                "gas": 500000, "chainId": self._network_id,
            }
            signed = w3.eth.account.sign_transaction(tx, private_key.key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status != 1:
                return TradeResult(
                    success=False, tx_hash=tx_hash.hex(), input_amount=quote.input_amount,
                    output_amount=None, error_message="Transaction reverted", explorer_url=self.get_explorer_url(tx_hash.hex()),
                )

            return TradeResult(
                success=True, tx_hash=tx_hash.hex(), input_amount=quote.input_amount,
                output_amount=quote.expected_output, error_message=None,
                explorer_url=self.get_explorer_url(tx_hash.hex()),
            )
        except Exception as e:
            return TradeResult(
                success=False, tx_hash=None, input_amount=quote.input_amount,
                output_amount=None, error_message=str(e), explorer_url=None,
            )


myriad_platform = MyriadPlatform()
