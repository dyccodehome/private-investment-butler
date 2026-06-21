"""Read-only health checks for Longbridge integration."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from src.longbridge_capabilities import list_denied_capabilities, list_read_capabilities
from src.longbridge_provider import longbridge_env, longbridge_log_path


OPENAPI_HOST = "openapi.longbridge.com"
OPENAPI_PORT = 443
READONLY_HEALTH_COMMANDS = {
    "positions": ["longbridge", "positions", "--format", "json"],
    "watchlist": ["longbridge", "watchlist", "--format", "json"],
}


def run_longbridge_health(
    *,
    timeout_seconds: int = 8,
    run_cli: bool = True,
    run_network: bool = True,
) -> dict[str, Any]:
    """Run Longbridge diagnostics without using any trading-write capability."""

    timeout = max(1, int(timeout_seconds or 8))
    checks: list[dict[str, Any]] = []
    cli_path = shutil.which("longbridge")

    checks.append(
        _check_result(
            name="cli_binary",
            status="ok" if cli_path else "error",
            message=cli_path or "未找到 longbridge CLI。请先安装并执行 longbridge auth login。",
            category="" if cli_path else "cli_missing",
        )
    )
    checks.append(_check_log_path())
    if run_network:
        checks.append(_check_network(timeout_seconds=timeout))
    else:
        checks.append(_check_result("network", "skipped", "已按参数跳过网络检查。"))

    if run_cli and cli_path:
        for name, command in READONLY_HEALTH_COMMANDS.items():
            checks.append(_check_cli_command(name=name, command=command, timeout_seconds=timeout))
    elif not run_cli:
        checks.append(_check_result("cli_read_commands", "skipped", "已按参数跳过长桥只读命令检查。"))

    status = _overall_status(checks)
    return {
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "status": status,
        "openapi_host": OPENAPI_HOST,
        "timeout_seconds": timeout,
        "checks": checks,
        "capabilities": {
            "implemented_read": list_read_capabilities(include_planned=False),
            "planned_read": [
                item for item in list_read_capabilities(include_planned=True) if not item.get("implemented")
            ],
            "denied_write": list_denied_capabilities(),
        },
        "findings": _build_findings(checks),
    }


def format_longbridge_health(result: dict[str, Any]) -> str:
    checks = list(result.get("checks") or [])
    capabilities = result.get("capabilities") or {}
    implemented_read = capabilities.get("implemented_read") or []
    planned_read = capabilities.get("planned_read") or []
    denied_write = capabilities.get("denied_write") or []
    lines = [
        "长桥健康检查",
        f"生成时间：{result.get('generated_at')}",
        f"总体状态：{result.get('status')}",
        f"OpenAPI：{result.get('openapi_host')}",
        "",
        "检查项：",
    ]
    for check in checks:
        suffix = f" [{check.get('category')}]" if check.get("category") else ""
        lines.append(f"- {check.get('status')} {check.get('name')}：{check.get('message')}{suffix}")

    lines.extend(
        [
            "",
            "能力边界：",
            f"- 已实现只读能力：{len(implemented_read)}",
            f"- 规划中只读能力：{len(planned_read)}",
            f"- 永久禁止交易写能力：{len(denied_write)}",
        ]
    )
    denied_ids = [str(item.get("capability_id")) for item in denied_write]
    if denied_ids:
        lines.append(f"- 禁止清单：{', '.join(denied_ids)}")

    findings = list(result.get("findings") or [])
    if findings:
        lines.extend(["", "结论："])
        lines.extend(f"- {item}" for item in findings)
    return "\n".join(lines).strip()


def _check_log_path() -> dict[str, Any]:
    path = longbridge_log_path()
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".health_check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return _check_result(
            name="log_path",
            status="error",
            message=f"{path} 不可写：{exc}",
            category="log_permission",
        )
    return _check_result(name="log_path", status="ok", message=f"{path} 可写")


def _check_network(*, timeout_seconds: int) -> dict[str, Any]:
    sock = None
    try:
        sock = socket.create_connection((OPENAPI_HOST, OPENAPI_PORT), timeout=timeout_seconds)
    except OSError as exc:
        return _check_result(
            name="openapi_network",
            status="error",
            message=str(exc),
            category="network_or_dns",
        )
    finally:
        if sock is not None:
            sock.close()
    return _check_result(name="openapi_network", status="ok", message=f"{OPENAPI_HOST}:{OPENAPI_PORT} 可连接")


def _check_cli_command(*, name: str, command: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            env=longbridge_env(),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return _check_result(name=name, status="error", message=f"{' '.join(command)} 执行超时", category="timeout")
    except OSError as exc:
        return _check_result(name=name, status="error", message=str(exc), category=_classify_error(str(exc)))

    output = (completed.stdout or "").strip()
    detail = (completed.stderr or output or "").strip()
    if completed.returncode != 0:
        return _check_result(
            name=name,
            status="error",
            message=_truncate(detail or str(completed.returncode), 220),
            category=_classify_error(detail),
        )
    if output and not _looks_like_json(output):
        return _check_result(
            name=name,
            status="warn",
            message="命令返回非 JSON 输出，需确认 CLI --format json 是否生效。",
            category="invalid_json",
        )
    return _check_result(name=name, status="ok", message=f"{' '.join(command)} 可执行")


def _looks_like_json(value: str) -> bool:
    try:
        json.loads(value)
    except json.JSONDecodeError:
        return False
    return True


def _check_result(name: str, status: str, message: str, *, category: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "category": category,
    }


def _overall_status(checks: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status") or "") for item in checks}
    if "error" in statuses:
        return "error"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _build_findings(checks: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    categories = {str(item.get("category") or "") for item in checks}
    if "cli_missing" in categories:
        findings.append("本机未找到 longbridge CLI，所有长桥同步都会失败。")
    if "log_permission" in categories:
        findings.append("长桥日志目录不可写，这会导致 CLI 启动时失败；需要修复 LONGBRIDGE_LOG_PATH 权限。")
    if "network_or_dns" in categories:
        findings.append("无法连接长桥 OpenAPI，可能是网络、DNS、代理、证书或当前运行沙箱限制。")
    if "auth" in categories:
        findings.append("长桥认证可能失效，需要重新执行 longbridge auth login 或检查环境配置。")
    if "timeout" in categories:
        findings.append("长桥 CLI 调用超时，需要确认网络质量或增加 timeout。")
    if not findings:
        findings.append("长桥 CLI、日志路径和只读基础命令未发现阻塞。")
    findings.append("交易写能力仍在禁止清单内，健康检查不会执行下单、改单或撤单。")
    return findings


def _classify_error(text: str) -> str:
    lower = text.lower()
    if "permissiondenied" in lower or "permission denied" in lower or "operation not permitted" in lower:
        return "log_permission"
    if "auth" in lower or "unauthorized" in lower or "forbidden" in lower:
        return "auth"
    if "connect" in lower or "dns" in lower or "nodename" in lower or "resolve" in lower:
        return "network_or_dns"
    if "json" in lower:
        return "invalid_json"
    return "cli_error"


def _truncate(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."
