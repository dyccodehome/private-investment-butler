#!/usr/bin/env python3
"""Run Growth_Engine daily market review.

Examples:
  python3 scripts/run_growth_daily_review.py --market US --chat-id oc_xxx
  FEISHU_DEFAULT_CHAT_ID=oc_xxx python3 scripts/run_growth_daily_review.py --market US
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import communication_gate
from src.app_config import get_config
from src.growth_portfolio import review_growth_daily


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Growth_Engine daily review.")
    parser.add_argument("--market", required=True, choices=["US"], help="Market to review.")
    parser.add_argument("--chat-id", default="", help="Feishu chat_id to send the report to.")
    args = parser.parse_args()

    chat_id = args.chat_id or get_config().messaging().default_chat_id
    report = review_growth_daily(args.market, chat_id=chat_id or None)
    if chat_id:
        communication_gate.send(chat_id, report)
    print(report)


if __name__ == "__main__":
    main()
