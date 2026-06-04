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
    source_chain: list[dict[str, Any]] = field(default_factory=list)
    data_quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ok_result(
    *,
    source: str,
    market: str,
    symbol: str,
    data: dict[str, Any],
    source_chain: list[dict[str, Any]] | None = None,
    data_quality: dict[str, Any] | None = None,
) -> MarketDataResult:
    return MarketDataResult(
        status="ok",
        source=source,
        market=market,
        symbol=symbol,
        data=data,
        error="",
        source_chain=source_chain or [],
        data_quality=data_quality or {},
    )


def error_result(
    *,
    source: str,
    market: str,
    symbol: str,
    error: str,
    data: dict[str, Any] | None = None,
    source_chain: list[dict[str, Any]] | None = None,
    data_quality: dict[str, Any] | None = None,
) -> MarketDataResult:
    return MarketDataResult(
        status="error",
        source=source,
        market=market,
        symbol=symbol,
        data=data or {},
        error=error,
        source_chain=source_chain or [],
        data_quality=data_quality or {},
    )
