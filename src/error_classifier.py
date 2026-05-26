"""集中式错误分类与用户可读恢复建议。

借鉴 Hermes 的错误分类器，把分散的字符串判断收敛到一个模块。
主管道只关心分类结果，不再把 OpenAI/网络/额度错误以堆栈形式暴露给用户。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorKind(str, Enum):
    """管道错误分类，用于决定恢复建议。"""

    BILLING = "billing"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    TIMEOUT = "timeout"
    NETWORK = "network"
    CONTEXT_OVERFLOW = "context_overflow"
    MODEL_NOT_FOUND = "model_not_found"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedError:
    """结构化错误分类结果。"""

    kind: ErrorKind
    retryable: bool
    user_message: str
    raw_message: str


_BILLING_PATTERNS = [
    "insufficient_quota",
    "insufficient credits",
    "exceeded your current quota",
    "billing",
    "payment required",
    "credit balance",
]

_RATE_LIMIT_PATTERNS = [
    "rate limit",
    "too many requests",
    "throttled",
    "try again",
]

_AUTH_PATTERNS = [
    "invalid api key",
    "incorrect api key",
    "unauthorized",
    "forbidden",
    "401",
    "403",
]

_NETWORK_PATTERNS = [
    "urlopen error",
    "temporary failure",
    "certificate_verify_failed",
    "nodename nor servname",
]

_TIMEOUT_PATTERNS = [
    "timed out",
    "timeout",
    "read operation timed out",
]

_CONTEXT_PATTERNS = [
    "context length",
    "too many tokens",
    "maximum context",
    "prompt is too long",
]

_MODEL_PATTERNS = [
    "model_not_found",
    "model not found",
    "invalid model",
    "does not exist",
]


def classify_error(exc: BaseException) -> ClassifiedError:
    """把异常转换为可展示、可记录、可决策的错误分类。"""

    raw = str(exc)
    text = raw.lower()

    if _contains_any(text, _BILLING_PATTERNS):
        return ClassifiedError(
            kind=ErrorKind.BILLING,
            retryable=False,
            user_message="模型调用被账单或额度拦截。请检查当前模型厂商的 Billing、Credits 或 Usage Limit 后重试。",
            raw_message=raw,
        )
    if _contains_any(text, _RATE_LIMIT_PATTERNS):
        return ClassifiedError(
            kind=ErrorKind.RATE_LIMIT,
            retryable=True,
            user_message="模型服务触发限流。建议稍后重试，或降低并发和单次输出 token 上限。",
            raw_message=raw,
        )
    if _contains_any(text, _AUTH_PATTERNS):
        return ClassifiedError(
            kind=ErrorKind.AUTH,
            retryable=False,
            user_message="模型鉴权失败。请检查本地 .env 中的 API Key 是否正确、是否有权限调用当前模型。",
            raw_message=raw,
        )
    if _contains_any(text, _TIMEOUT_PATTERNS):
        return ClassifiedError(
            kind=ErrorKind.TIMEOUT,
            retryable=True,
            user_message="模型响应超时。当前模型可能推理较慢，建议提高 timeout、降低 max_output_tokens 或把审计 prompt 压缩后重试。",
            raw_message=raw,
        )
    if _contains_any(text, _NETWORK_PATTERNS):
        return ClassifiedError(
            kind=ErrorKind.NETWORK,
            retryable=True,
            user_message="模型网络请求失败。请检查网络、代理或本机证书链配置后重试。",
            raw_message=raw,
        )
    if _contains_any(text, _CONTEXT_PATTERNS):
        return ClassifiedError(
            kind=ErrorKind.CONTEXT_OVERFLOW,
            retryable=True,
            user_message="上下文过长导致模型拒绝。建议压缩策略文件、减少披露数据或降低历史注入量。",
            raw_message=raw,
        )
    if _contains_any(text, _MODEL_PATTERNS):
        return ClassifiedError(
            kind=ErrorKind.MODEL_NOT_FOUND,
            retryable=False,
            user_message="当前模型不可用或名称不正确。请检查 config.yaml 中的模型配置。",
            raw_message=raw,
        )

    return ClassifiedError(
        kind=ErrorKind.UNKNOWN,
        retryable=True,
        user_message="管道遇到未分类异常。已写入本地会话记录，请查看日志后重试。",
        raw_message=raw,
    )


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)
