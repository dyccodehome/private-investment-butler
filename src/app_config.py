"""应用统一配置管理。

密钥绝不存放在本文件或 ``config.yaml`` 中。YAML 文件只声明默认值和环境变量名；
运行时从环境变量读取真实值，方便不同部署环境独立配置凭据。
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.init import PROJECT_ROOT


CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_CONFIG: dict[str, Any] = {
    "openai": {
        "provider": "openai",
        "api_protocol": "responses",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com",
        "responses_path": "/v1/responses",
        "chat_completions_path": "/v1/chat/completions",
        "default_model": "gpt-5.5",
        "default_reasoning_effort": "medium",
        "default_max_output_tokens": 4096,
        "timeout_seconds": 60,
    },
    "deepseek": {
        "provider": "deepseek",
        "api_protocol": "chat_completions",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "responses_path": "/v1/responses",
        "chat_completions_path": "/v1/chat/completions",
        "default_model": "deepseek-v4-pro",
        "default_reasoning_effort": "medium",
        "default_max_output_tokens": 4096,
        "timeout_seconds": 180,
    },
    "gemini": {
        "provider": "gemini",
        "api_protocol": "gemini_generate_content",
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com",
        "responses_path": "/v1beta/models/{model}:generateContent",
        "chat_completions_path": "/v1/chat/completions",
        "default_model": "gemini-2.5-pro",
        "default_reasoning_effort": "medium",
        "default_max_output_tokens": 4096,
        "timeout_seconds": 60,
    },
    "router": {"max_route_retries": 3},
    "frameworks": {
        "Cash_Anchor": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "reasoning_effort": "medium",
            "max_output_tokens": 4096,
        },
        "Growth_Engine": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "reasoning_effort": "high",
            "max_output_tokens": 4096,
        },
    },
    "agents": {
        "auditor": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "reasoning_effort": "high",
            "max_output_tokens": 1600,
        },
        "knowledge_absorber": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "reasoning_effort": "high",
            "max_output_tokens": 2400,
        },
    },
        "messaging": {
            "provider": "feishu",
            "app_id_env": "FEISHU_APP_ID",
            "app_secret_env": "FEISHU_APP_SECRET",
            "lark_host": "https://open.feishu.cn",
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
    "cost_management": {
        "currency": "USD",
        "daily_budget_usd": 5.0,
        "warning_threshold": 0.8,
        "model_prices": {
            "openai": {
                "gpt-5.5": {
                    "input_per_1m": 0,
                    "output_per_1m": 0,
                    "reasoning_per_1m": 0,
                }
            },
            "deepseek": {
                "deepseek-v4-pro": {
                    "input_per_1m": 0,
                    "output_per_1m": 0,
                    "reasoning_per_1m": 0,
                }
            },
            "gemini": {
                "gemini-2.5-pro": {
                    "input_per_1m": 0,
                    "output_per_1m": 0,
                    "reasoning_per_1m": 0,
                }
            },
        },
    },
}


@dataclass(frozen=True)
class LLMProviderSettings:
    """单个模型厂商的运行时配置。"""

    provider: str
    api_protocol: str
    api_key_env: str
    api_key: str = field(repr=False)
    base_url: str
    responses_path: str
    chat_completions_path: str
    default_model: str
    default_reasoning_effort: str
    default_max_output_tokens: int
    timeout_seconds: int


@dataclass(frozen=True)
class FrameworkLLMSettings:
    """每个策略框架独立的模型选择参数。"""

    provider: str
    model: str
    reasoning_effort: str
    max_output_tokens: int


@dataclass(frozen=True)
class MessagingSettings:
    """消息发送与飞书校验的运行时配置。"""

    provider: str
    app_id: str = field(repr=False)
    app_secret: str = field(repr=False)
    lark_host: str
    verification_token: str = field(repr=False)
    encrypt_key: str = field(repr=False)


class AppConfig:
    """对 ``config.yaml`` 和环境变量的类型化访问封装。"""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        _load_env_file(ENV_PATH)
        self.path = path
        self.raw = _deep_merge(DEFAULT_CONFIG, _load_config_file(path))

    def llm_provider(self, provider: str | None) -> LLMProviderSettings:
        """读取指定模型厂商配置。

        当前支持 openai、deepseek、gemini。新增厂商时只需要在 DEFAULT_CONFIG/config.yaml
        增加同名段，并在 ``src.llm_client`` 中补一个协议适配器。
        """

        provider_name = provider or "openai"
        section = self.raw.get(provider_name)
        if not isinstance(section, dict):
            raise ValueError(f"未知 LLM provider: {provider_name}")
        return LLMProviderSettings(
            provider=str(section.get("provider") or provider_name),
            api_protocol=str(section.get("api_protocol") or "responses"),
            api_key_env=str(section["api_key_env"]),
            api_key=os.getenv(str(section["api_key_env"]), ""),
            base_url=str(section["base_url"]).rstrip("/"),
            responses_path=str(section.get("responses_path") or "/v1/responses"),
            chat_completions_path=str(section.get("chat_completions_path") or "/v1/chat/completions"),
            default_model=str(section["default_model"]),
            default_reasoning_effort=str(section["default_reasoning_effort"]),
            default_max_output_tokens=int(section["default_max_output_tokens"]),
            timeout_seconds=int(section["timeout_seconds"]),
        )

    def openai(self) -> LLMProviderSettings:
        """兼容旧代码：返回 OpenAI provider 配置。"""

        return self.llm_provider("openai")

    def framework_llm(self, framework_id: str | None) -> FrameworkLLMSettings:
        default_provider = self.llm_provider("deepseek")
        section = self.raw.get("frameworks", {}).get(framework_id or "", {})
        provider = str(section.get("provider") or default_provider.provider)
        provider_settings = self.llm_provider(provider)
        return FrameworkLLMSettings(
            provider=provider,
            model=str(section.get("model") or provider_settings.default_model),
            reasoning_effort=str(
                section.get("reasoning_effort") or provider_settings.default_reasoning_effort
            ),
            max_output_tokens=int(section.get("max_output_tokens") or provider_settings.default_max_output_tokens),
        )

    def agent_llm(self, agent_role: str, framework_id: str | None = None) -> FrameworkLLMSettings:
        """读取 Agent 角色级模型配置；没有角色配置时回退到策略框架配置。"""

        section = self.raw.get("agents", {}).get(agent_role, {})
        if not section:
            return self.framework_llm(framework_id)
        provider = str(section.get("provider") or "deepseek")
        provider_settings = self.llm_provider(provider)
        return FrameworkLLMSettings(
            provider=provider,
            model=str(section.get("model") or provider_settings.default_model),
            reasoning_effort=str(
                section.get("reasoning_effort") or provider_settings.default_reasoning_effort
            ),
            max_output_tokens=int(section.get("max_output_tokens") or provider_settings.default_max_output_tokens),
        )

    def messaging(self) -> MessagingSettings:
        section = self.raw["messaging"]
        return MessagingSettings(
            provider=str(section.get("provider", "feishu")),
            app_id=os.getenv(str(section.get("app_id_env", "FEISHU_APP_ID")), ""),
            app_secret=os.getenv(str(section.get("app_secret_env", "FEISHU_APP_SECRET")), ""),
            lark_host=str(section.get("lark_host", "https://open.feishu.cn")).rstrip("/"),
            verification_token=os.getenv(str(section["verification_token_env"]), ""),
            encrypt_key=os.getenv(str(section["encrypt_key_env"]), ""),
        )

    def token_monitor(self) -> dict[str, Any]:
        """以普通字典形式返回 Token 监控配置。"""

        return dict(self.raw.get("token_monitor", {}))

    def cost_management(self) -> dict[str, Any]:
        """以普通字典形式返回成本管理配置。"""

        return dict(self.raw.get("cost_management", {}))


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
