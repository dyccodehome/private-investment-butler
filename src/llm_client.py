"""统一 LLM 网关。

Agent 其他模块只调用这一层，不直接依赖厂商 SDK 或具体 HTTP 协议。
凭据和模型默认值统一来自 ``src.app_config``。
"""

from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from src.app_config import FrameworkLLMSettings, LLMProviderSettings, get_config
from src import communication_gate
from src.cost_meter import budget_warning
from src.token_monitor import build_token_warning, record_token_usage
from src.trace_logger import trace_event


SYSTEM_CA_PATH = Path("/etc/ssl/cert.pem")


@dataclass(frozen=True)
class LLMConfig:
    """单次模型调用的运行时参数。"""

    provider: str
    model: str
    reasoning_effort: str
    max_output_tokens: int


class LLMClient:
    """支持多厂商的轻量 LLM 客户端。"""

    def __init__(self, config: LLMConfig | None = None) -> None:
        """使用显式配置或项目默认值创建客户端。"""

        app_config = get_config()
        self.config = config or _default_llm_config(app_config.llm_provider("deepseek"))
        self.provider_settings = app_config.llm_provider(self.config.provider)
        self.api_key = self.provider_settings.api_key
        self.base_url = self.provider_settings.base_url
        self.timeout_seconds = self.provider_settings.timeout_seconds

    @classmethod
    def for_framework(cls, framework_id: str | None) -> "LLMClient":
        """按策略框架专属模型配置创建客户端。"""

        settings: FrameworkLLMSettings = get_config().framework_llm(framework_id)
        return cls.from_settings(settings)

    @classmethod
    def for_agent(cls, agent_role: str, framework_id: str | None = None) -> "LLMClient":
        """按 Agent 角色专属模型配置创建客户端。

        审计官这类横向切面应使用角色级配置，确保它和 Worker 在模型选择上物理隔离。
        """

        settings: FrameworkLLMSettings = get_config().agent_llm(agent_role, framework_id)
        return cls.from_settings(settings)

    @classmethod
    def from_settings(cls, settings: FrameworkLLMSettings) -> "LLMClient":
        """从类型化模型配置创建客户端。"""

        return cls(
            LLMConfig(
                provider=settings.provider,
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
        trace_id: str | None = None,
    ) -> str:
        """调用配置中的 LLM provider 并返回纯文本。

        如果尚未配置对应厂商 API Key，返回清晰的占位提示，
        让其余管道在配置凭据前仍可测试。
        """

        if not self.api_key:
            record_token_usage(
                provider=self.config.provider,
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
                error=f"{self.provider_settings.api_key_env} is not configured",
                trace_id=trace_id,
            )
            trace_event(
                trace_id=trace_id,
                event_type="llm_call_finished",
                chat_id=chat_id,
                framework_id=framework_id,
                agent_role=agent_role,
                status="not_configured",
                input_preview=user_query or user_prompt,
                output_preview=f"{self.provider_settings.api_key_env} is not configured",
                metadata={
                    "provider": self.config.provider,
                    "model": self.config.model,
                    "call_site": call_site,
                },
            )
            return (
                f"[{self.config.provider.upper()}_NOT_CONFIGURED]\n"
                f"请先配置 {self.provider_settings.api_key_env}。\n"
                f"provider={self.config.provider}, model={self.config.model}, "
                f"reasoning_effort={self.config.reasoning_effort}"
            )

        payload = self._build_payload(system_prompt, user_prompt)

        started_at = time.perf_counter()
        try:
            response = self._post_json(payload)
        except RuntimeError as exc:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            record_token_usage(
                provider=self.config.provider,
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
                latency_ms=latency_ms,
                status="error",
                error=str(exc),
                trace_id=trace_id,
            )
            trace_event(
                trace_id=trace_id,
                event_type="llm_call_finished",
                chat_id=chat_id,
                framework_id=framework_id,
                agent_role=agent_role,
                status="error",
                latency_ms=latency_ms,
                input_preview=user_query or user_prompt,
                metadata={
                    "provider": self.config.provider,
                    "model": self.config.model,
                    "call_site": call_site,
                },
                error=str(exc),
            )
            raise

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        record_token_usage(
            provider=self.config.provider,
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
            latency_ms=latency_ms,
            status="success",
            trace_id=trace_id,
        )
        usage = _extract_usage_summary(response)
        trace_event(
            trace_id=trace_id,
            event_type="llm_call_finished",
            chat_id=chat_id,
            framework_id=framework_id,
            agent_role=agent_role,
            status="success",
            latency_ms=latency_ms,
            input_preview=user_query or user_prompt,
            output_preview=_extract_response_text(response),
            token_usage={
                "provider": self.config.provider,
                "model": self.config.model,
                **usage,
            },
            risk_flags=_llm_risk_flags(response, usage),
            metadata={"call_site": call_site},
        )
        try:
            from src.budget_manager import record_budget_usage

            record_budget_usage(
                trace_id=trace_id,
                chat_id=chat_id,
                framework_id=framework_id,
                call_site=call_site,
                token_usage=usage,
            )
        except Exception:
            pass
        warning = build_token_warning(chat_id)
        if warning and chat_id:
            communication_gate.send(chat_id, warning)
        cost_warning = budget_warning()
        if cost_warning and chat_id:
            communication_gate.send(chat_id, cost_warning)
        return _extract_response_text(response)

    def _build_payload(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """按厂商协议构造请求体。"""

        protocol = self.provider_settings.api_protocol
        if protocol == "responses":
            return {
                "model": self.config.model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "reasoning": {"effort": self.config.reasoning_effort},
                "max_output_tokens": self.config.max_output_tokens,
            }
        if protocol == "chat_completions":
            return {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": self.config.max_output_tokens,
            }
        if protocol == "gemini_generate_content":
            return {
                "systemInstruction": {
                    "parts": [{"text": system_prompt}],
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": user_prompt}],
                    }
                ],
                "generationConfig": {
                    "maxOutputTokens": self.config.max_output_tokens,
                },
            }
        raise ValueError(f"不支持的 LLM api_protocol: {protocol}")

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        """只使用 Python 标准库向模型厂商 POST 一次请求。"""

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = self._request_url()
        headers = {"Content-Type": "application/json"}
        if self.provider_settings.api_protocol != "gemini_generate_content":
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = request.Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds, context=_ssl_context()) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.config.provider} API HTTP {exc.code}: {detail}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"{self.config.provider} API request failed: {exc}") from exc

    def _request_url(self) -> str:
        """根据协议生成请求 URL。"""

        protocol = self.provider_settings.api_protocol
        if protocol == "responses":
            return f"{self.base_url}{self.provider_settings.responses_path}"
        if protocol == "chat_completions":
            return f"{self.base_url}{self.provider_settings.chat_completions_path}"
        if protocol == "gemini_generate_content":
            path = self.provider_settings.responses_path.format(model=self.config.model)
            separator = "&" if "?" in path else "?"
            return f"{self.base_url}{path}{separator}key={parse.quote(self.api_key)}"
        raise ValueError(f"不支持的 LLM api_protocol: {protocol}")


def _extract_response_text(response: dict[str, Any]) -> str:
    """从常见 LLM JSON 结构中提取文本。"""

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

    choices = response.get("choices") or []
    for choice in choices:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(content)
    if chunks:
        return "\n".join(chunks)

    for candidate in response.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "\n".join(chunks)

    return json.dumps(response, ensure_ascii=False)


def _extract_usage_summary(response: dict[str, Any]) -> dict[str, int]:
    """为 Trace 事件提取统一 token 字段。"""

    usage = response.get("usage") or {}
    gemini_usage = response.get("usageMetadata") or {}
    input_tokens = int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or gemini_usage.get("promptTokenCount")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or gemini_usage.get("candidatesTokenCount")
        or 0
    )
    output_details = usage.get("output_tokens_details") or {}
    reasoning_tokens = int(
        output_details.get("reasoning_tokens")
        or usage.get("reasoning_tokens")
        or gemini_usage.get("thoughtsTokenCount")
        or 0
    )
    total_tokens = int(usage.get("total_tokens") or gemini_usage.get("totalTokenCount") or input_tokens + output_tokens)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


def _llm_risk_flags(response: dict[str, Any], usage: dict[str, int]) -> list[str]:
    """根据调用结果打上低成本风险标签。"""

    flags: list[str] = []
    if usage.get("total_tokens", 0) >= 12000:
        flags.append("high_token_call")
    if not _extract_response_text(response).strip():
        flags.append("empty_llm_output")
    return flags


def _default_llm_config(provider_settings: LLMProviderSettings) -> LLMConfig:
    """根据 provider 默认值构造客户端配置。"""

    return LLMConfig(
        provider=provider_settings.provider,
        model=provider_settings.default_model,
        reasoning_effort=provider_settings.default_reasoning_effort,
        max_output_tokens=provider_settings.default_max_output_tokens,
    )


def _ssl_context() -> ssl.SSLContext:
    """创建 HTTPS 校验证书上下文。

    macOS 的 python.org 发行版有时不会自动指向系统 CA 文件。
    如果默认上下文没有 cafile，则使用系统证书链，不降低 TLS 校验强度。
    """

    paths = ssl.get_default_verify_paths()
    if paths.cafile:
        return ssl.create_default_context()
    if SYSTEM_CA_PATH.exists():
        return ssl.create_default_context(cafile=str(SYSTEM_CA_PATH))
    return ssl.create_default_context()
