"""Unified read-only market data providers."""

from src.market_data.models import MarketDataResult
from src.market_data.provider_router import fetch_market_data, fetch_quote

__all__ = ["MarketDataResult", "fetch_market_data", "fetch_quote"]
