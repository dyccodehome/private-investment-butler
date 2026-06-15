#!/usr/bin/env python3
"""Refresh local trading calendar cache."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.trading_calendar import build_trading_calendar, save_trading_calendar


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh local trading calendar cache.")
    parser.add_argument("--market", choices=["CN", "US", "ALL"], default="ALL", help="Market to refresh.")
    parser.add_argument("--year", type=int, default=date.today().year, help="Calendar year.")
    parser.add_argument("--refresh", action="store_true", help="Rebuild even if cache exists.")
    args = parser.parse_args()

    markets = ["CN", "US"] if args.market == "ALL" else [args.market]
    for market in markets:
        payload = build_trading_calendar(market, args.year, refresh=args.refresh, allow_fetch=True)
        path = save_trading_calendar(payload)
        warnings = payload.get("warnings") or []
        print(
            f"{market} {args.year}: {len(payload.get('trading_days') or [])} trading days, "
            f"source={payload.get('source')}, path={path}"
        )
        for warning in warnings:
            print(f"- warning: {warning}")


if __name__ == "__main__":
    main()
