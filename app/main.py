from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.platforms.registry import platform_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    await platform_registry.initialize_all()
    yield
    await platform_registry.close_all()


app = FastAPI(
    title="Spredd Developer API",
    description="Prediction market trading API — market data, quotes, trade execution, positions, and arbitrage across Kalshi, Polymarket, Myriad, Opinion, and Limitless.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routes import arbitrage, auth, markets, positions, trading, usage  # noqa: E402

app.include_router(auth.router, prefix="/v1/auth", tags=["Auth"])
app.include_router(markets.router, prefix="/v1", tags=["Markets"])
app.include_router(trading.router, prefix="/v1/trading", tags=["Trading"])
app.include_router(positions.router, prefix="/v1", tags=["Positions"])
app.include_router(arbitrage.router, prefix="/v1", tags=["Arbitrage"])
app.include_router(usage.router, prefix="/v1", tags=["Usage"])


@app.get("/health")
async def health():
    return {"status": "ok"}
