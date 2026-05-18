"""OpenAI Responses API 网关。

Agent 其他模块只调用这一层，不直接依赖厂商 SDK。
凭据和模型默认值统一来自 ``src.app_config``。
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
    """单次 OpenAI 模型调用的运行时参数。"""

    model: str
    reasoning_effort: str
    max_output_tokens: int


class LLMClient:
    """基于 Responses API 的轻量 OpenAI 客户端。"""

    def __init__(self, config: LLMConfig | None = None) -> None:
        """使用显式配置或项目默认值创建客户端。"""

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
        """按策略框架专属模型配置创建客户端。"""

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
        context_bundle_id: str | None = None,
        chat_id: str | None = None,
        user_query: str | None = None,
    ) -> str:
        """调用 OpenAI 并返回纯文本。

        如果尚未配置 ``OPENAI_API_KEY``，返回清晰的占位提示，
        让其余管道在配置凭据前仍可测试。
        """

        if not self.api_key:
            record_token_usage(
                model=self.config.model,
                agent_role=agent_role,
                call_site=call_site,
                framework_id=framework_id,
                context_bundle_id=context_bundle_id,
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
                context_bundle_id=context_bundle_id,
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
            context_bundle_id=context_bundle_id,
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
        """只使用 Python 标准库向 OpenAI POST 一次请求。"""

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
    """从常见 Responses API JSON 结构中提取文本。"""

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
