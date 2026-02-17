from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/spredd_api"

    # Solana
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"

    # EVM RPCs
    polygon_rpc_url: str = "https://polygon-rpc.com"
    bsc_rpc_url: str = "https://bsc-dataseed.binance.org"
    base_rpc_url: str = "https://mainnet.base.org"
    abstract_rpc_url: str = "https://api.mainnet.abs.xyz"
    linea_rpc_url: str = "https://rpc.linea.build"

    # DFlow / Kalshi
    dflow_api_key: str = ""
    dflow_api_base_url: str = "https://c.quote-api.dflow.net"
    dflow_metadata_url: str = "https://c.prediction-markets-api.dflow.net"

    # Polymarket
    polymarket_api_url: str = "https://clob.polymarket.com"
    polymarket_builder_key: str = ""
    polymarket_builder_secret: str = ""
    polymarket_builder_passphrase: str = ""

    # Opinion Labs
    opinion_api_url: str = "https://proxy.opinion.trade:8443"
    opinion_api_key: str = ""
    opinion_multi_sig_addr: str = ""

    # Limitless
    limitless_api_key: str = ""
    limitless_api_url: str = "https://api.limitless.exchange"

    # Myriad
    myriad_api_key: str = ""
    myriad_api_url: str = "https://api-v2.myriadprotocol.com"
    myriad_referral_code: str = ""
    myriad_network_id: int = 2741

    # Fee collection
    kalshi_fee_account: str = ""
    kalshi_fee_bps: int = 50
    evm_fee_account: str = ""
    evm_fee_bps: int = 50

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
