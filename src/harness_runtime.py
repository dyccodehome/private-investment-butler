"""Harness Runtime facade.

The current pipeline still lives in main.py. This facade gives the project a
stable Runtime concept without forcing a disruptive orchestration rewrite.
"""

from __future__ import annotations

from src.state import AgentState


class HarnessRuntime:
    """Thin runtime wrapper around the existing explicit Python pipeline."""

    def run(self, user_input: str, chat_id: str = "cli") -> AgentState:
        from main import run_pipeline

        return run_pipeline(user_input, chat_id=chat_id)


def run(user_input: str, chat_id: str = "cli") -> AgentState:
    """Convenience function for callers that want the Harness Runtime API."""

    return HarnessRuntime().run(user_input, chat_id=chat_id)
