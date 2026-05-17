"""OpenAI Responses API gateway.

The rest of the agent calls this boundary instead of importing vendor SDKs.
Credentials and model defaults come from ``src.app_config``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from src.app_config import FrameworkLLMSettings, get_config
from src import communication_gate
from src.token_monitor import build_token_warning, record_token_usage


@dataclass(frozen=True)
class LLMConfig:
    """Runtime knobs for one OpenAI model call."""

    model: str
    reasoning_effort: str
    max_output_tokens: int


class LLMClient:
    """Thin OpenAI client using the Responses API."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        """Create a client with explicit config or project defaults."""

        app_config = get_config()
        openai_settings = app_config.openai()
        self.api_key = openai_settings.api_key
        self.base_url = openai_settings.base_url
        self.responses_path = openai_settings.responses_path
        self.timeout_seconds = openai_settings.timeout_seconds
        self.config = config or LLMConfig(
            model=openai_settings.default_model,
            reasoning_effort=openai_settings.default_reasoning_effort,
            max_output_tokens=openai_settings.default_max_output_tokens,
        )

    @classmethod
    def for_framework(cls, framework_id: str | None) -> "LLMClient":
        """Create a client using framework-specific model settings."""

        settings: FrameworkLLMSettings = get_config().framework_llm(framework_id)
        return cls(
            LLMConfig(
                model=settings.model,
                reasoning_effort=settings.reasoning_effort,
                max_output_tokens=settings.max_output_tokens,
            )
        )

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        agent_role: str,
        call_site: str,
        framework_id: str | None = None,
        chat_id: str | None = None,
        user_query: str | None = None,
    ) -> str:
        """Call OpenAI and return plain text.

        If ``OPENAI_API_KEY`` is not configured yet, return a clear placeholder
        so the rest of the pipeline remains testable while credentials are
        being provisioned.
        """

        if not self.api_key:
            record_token_usage(
                model=self.config.model,
                agent_role=agent_role,
                call_site=call_site,
                framework_id=framework_id,
                chat_id=chat_id,
                user_query=user_query,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=None,
                latency_ms=0,
                status="not_configured",
                error="OPENAI_API_KEY is not configured",
            )
            return (
                "[OPENAI_NOT_CONFIGURED]\n"
                "请先配置 OPENAI_API_KEY。\n"
                f"model={self.config.model}, reasoning_effort={self.config.reasoning_effort}"
            )

        payload = {
            "model": self.config.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "reasoning": {"effort": self.config.reasoning_effort},
            "max_output_tokens": self.config.max_output_tokens,
        }

        started_at = time.perf_counter()
        try:
            response = self._post_json(payload)
        except RuntimeError as exc:
            record_token_usage(
                model=self.config.model,
                agent_role=agent_role,
                call_site=call_site,
                framework_id=framework_id,
                chat_id=chat_id,
                user_query=user_query,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=None,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                status="error",
                error=str(exc),
            )
            raise

        record_token_usage(
            model=self.config.model,
            agent_role=agent_role,
            call_site=call_site,
            framework_id=framework_id,
            chat_id=chat_id,
            user_query=user_query,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            status="success",
        )
        warning = build_token_warning(chat_id)
        if warning and chat_id:
            communication_gate.send(chat_id, warning)
        return _extract_response_text(response)

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST one request to OpenAI using only Python standard library."""

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{self.responses_path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}") from exc


def _extract_response_text(response: dict[str, Any]) -> str:
    """Extract text from common Responses API JSON shapes."""

    if isinstance(response.get("output_text"), str):
        return response["output_text"]

    chunks: list[str] = []
    for output in response.get("output", []) or []:
        for content in output.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "\n".join(chunks)

    return json.dumps(response, ensure_ascii=False)
