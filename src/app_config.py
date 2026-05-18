"""应用统一配置管理。

密钥绝不存放在本文件或 ``config.yaml`` 中。YAML 文件只声明默认值和环境变量名；
运行时从环境变量读取真实值，方便不同部署环境独立配置凭据。
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.init import PROJECT_ROOT


CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_CONFIG: dict[str, Any] = {
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com",
        "responses_path": "/v1/responses",
        "default_model": "gpt-5.5",
        "default_reasoning_effort": "medium",
        "default_max_output_tokens": 4096,
        "timeout_seconds": 60,
    },
    "router": {"max_route_retries": 3},
    "frameworks": {
        "Cash_Anchor": {
            "model": "gpt-5.5",
            "reasoning_effort": "medium",
            "max_output_tokens": 4096,
        },
        "CN_Alpha_Growth": {
            "model": "gpt-5.5",
            "reasoning_effort": "medium",
            "max_output_tokens": 4096,
        },
        "US_Disruptive_Growth": {
            "model": "gpt-5.5",
            "reasoning_effort": "high",
            "max_output_tokens": 4096,
        },
    },
    "messaging": {
        "provider": "feishu",
        "webhook_url_env": "FEISHU_WEBHOOK_URL",
        "verification_token_env": "FEISHU_VERIFICATION_TOKEN",
        "encrypt_key_env": "FEISHU_ENCRYPT_KEY",
    },
    "yuque": {
        "token_env": "YUQUE_TOKEN",
        "namespace_env": "YUQUE_NAMESPACE",
        "archive_dir_env": "YUQUE_ARCHIVE_DIR",
    },
    "iwencai": {
        "api_key_env": "IWENCAI_API_KEY",
        "api_url_env": "IWENCAI_API_URL",
    },
    "token_monitor": {
        "enabled": True,
        "daily_total_token_limit": 300000,
        "per_session_token_limit": 50000,
        "warning_threshold": 0.8,
    },
}


@dataclass(frozen=True)
class OpenAISettings:
    """OpenAI Responses API 调用的运行时配置。"""

    api_key: str
    base_url: str
    responses_path: str
    default_model: str
    default_reasoning_effort: str
    default_max_output_tokens: int
    timeout_seconds: int


@dataclass(frozen=True)
class FrameworkLLMSettings:
    """每个策略框架独立的模型选择参数。"""

    model: str
    reasoning_effort: str
    max_output_tokens: int


@dataclass(frozen=True)
class MessagingSettings:
    """消息发送与飞书校验的运行时配置。"""

    provider: str
    webhook_url: str
    verification_token: str
    encrypt_key: str


class AppConfig:
    """对 ``config.yaml`` 和环境变量的类型化访问封装。"""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        _load_env_file(ENV_PATH)
        self.path = path
        self.raw = _deep_merge(DEFAULT_CONFIG, _load_config_file(path))

    def openai(self) -> OpenAISettings:
        section = self.raw["openai"]
        return OpenAISettings(
            api_key=os.getenv(section["api_key_env"], ""),
            base_url=str(section["base_url"]).rstrip("/"),
            responses_path=str(section["responses_path"]),
            default_model=str(section["default_model"]),
            default_reasoning_effort=str(section["default_reasoning_effort"]),
            default_max_output_tokens=int(section["default_max_output_tokens"]),
            timeout_seconds=int(section["timeout_seconds"]),
        )

    def framework_llm(self, framework_id: str | None) -> FrameworkLLMSettings:
        openai = self.openai()
        section = self.raw.get("frameworks", {}).get(framework_id or "", {})
        return FrameworkLLMSettings(
            model=str(section.get("model") or openai.default_model),
            reasoning_effort=str(section.get("reasoning_effort") or openai.default_reasoning_effort),
            max_output_tokens=int(section.get("max_output_tokens") or openai.default_max_output_tokens),
        )

    def messaging(self) -> MessagingSettings:
        section = self.raw["messaging"]
        return MessagingSettings(
            provider=str(section.get("provider", "feishu")),
            webhook_url=os.getenv(str(section["webhook_url_env"]), ""),
            verification_token=os.getenv(str(section["verification_token_env"]), ""),
            encrypt_key=os.getenv(str(section["encrypt_key_env"]), ""),
        )

    def token_monitor(self) -> dict[str, Any]:
        """以普通字典形式返回 Token 监控配置。"""

        return dict(self.raw.get("token_monitor", {}))


def get_config() -> AppConfig:
    """返回新的配置视图，方便测试时动态修改环境变量。"""

    return AppConfig()


def _load_env_file(path: Path) -> None:
    """加载项目根目录的 ``.env``，但不覆盖外部已经注入的环境变量。"""

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_config_file(path: Path) -> dict[str, Any]:
    """优先用 PyYAML 加载项目配置；若未安装则使用轻量 fallback。"""

    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore  # 可选依赖：存在则使用，不存在则走轻量解析器。

        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}
    except ModuleNotFoundError:
        return _load_simple_yaml(path)


def _load_simple_yaml(path: Path) -> dict[str, Any]:
    """在没有依赖的情况下解析本项目有限的 YAML 结构。"""

    result: dict[str, Any] = {}
    current_top: str | None = None
    current_framework: str | None = None
    current_list_key: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0 and stripped.endswith(":"):
            current_top = stripped[:-1]
            result.setdefault(current_top, {})
            current_framework = None
            current_list_key = None
            continue

        if current_top == "frameworks" and indent == 2 and stripped.endswith(":"):
            current_framework = stripped[:-1]
            result["frameworks"].setdefault(current_framework, {})
            current_list_key = None
            continue

        if current_top == "frameworks" and current_framework and indent == 4:
            key, value = _split_key_value(stripped)
            if value is None:
                result["frameworks"][current_framework][key] = []
                current_list_key = key
            else:
                result["frameworks"][current_framework][key] = _parse_scalar(value)
            continue

        if current_top == "frameworks" and current_framework and current_list_key and indent == 6:
            if stripped.startswith("- "):
                result["frameworks"][current_framework][current_list_key].append(_parse_scalar(stripped[2:]))
            continue

        if current_top and indent == 2:
            key, value = _split_key_value(stripped)
            if value is not None:
                result[current_top][key] = _parse_scalar(value)

    return result


def _split_key_value(text: str) -> tuple[str, str | None]:
    if ":" not in text:
        return text, None
    key, value = text.split(":", 1)
    value = value.strip()
    return key.strip(), value if value else None


def _parse_scalar(value: str) -> Any:
    clean = value.strip().strip('"').strip("'")
    if clean.isdigit():
        return int(clean)
    try:
        return float(clean)
    except ValueError:
        return clean


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
