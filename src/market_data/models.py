from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarketDataResult:
    """统一市场数据返回结构。"""

    status: str
    source: str
    market: str
    symbol: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ok_result(*, source: str, market: str, symbol: str, data: dict[str, Any]) -> MarketDataResult:
    return MarketDataResult(status="ok", source=source, market=market, symbol=symbol, data=data, error="")


def error_result(*, source: str, market: str, symbol: str, error: str, data: dict[str, Any] | None = None) -> MarketDataResult:
    return MarketDataResult(status="error", source=source, market=market, symbol=symbol, data=data or {}, error=error)
