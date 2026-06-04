"""Shared data-quality summaries for disclosed facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def payload_data_quality(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a standard data-quality block for one Skill payload."""

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    embedded = payload.get("data_quality")
    if isinstance(embedded, dict) and embedded:
        return embedded
    embedded = data.get("data_quality")
    if isinstance(embedded, dict) and embedded:
        return embedded

    warnings = [str(item) for item in payload.get("warnings") or [] if str(item).strip()]
    error = str(payload.get("error") or "").strip()
    status = str(payload.get("status") or "missing")
    data_type = str(payload.get("data_type") or "unknown")
    coverage = {data_type: _coverage_from_status(status)}
    limitations = list(warnings)
    if error:
        limitations.append(error)
    return {
        "source_chain": _source_chain(payload),
        "freshness": _freshness_label(payload),
        "coverage": coverage,
        "limitations": _dedupe(limitations),
    }


def summarize_disclosures(disclosures: list[Any]) -> dict[str, Any]:
    """Summarize data quality across AgentState.disclosed_data."""

    coverage: dict[str, str] = {}
    source_chain: list[dict[str, Any]] = []
    limitations: list[str] = []
    stale_blocks: list[str] = []
    for disclosure in disclosures:
        payload = getattr(disclosure, "payload", None)
        if not isinstance(payload, dict):
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        if not isinstance(result, dict):
            continue
        quality = payload_data_quality(result)
        for key, value in (quality.get("coverage") or {}).items():
            coverage[str(key)] = str(value)
        for item in quality.get("source_chain") or []:
            if isinstance(item, dict):
                source_chain.append(dict(item))
        for item in quality.get("limitations") or []:
            limitations.append(str(item))
        freshness = quality.get("freshness")
        if freshness in {"stale", "unknown"}:
            stale_blocks.append(str(result.get("data_type") or result.get("source") or "unknown"))

    return {
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "coverage": coverage,
        "source_chain": source_chain,
        "limitations": _dedupe(limitations),
        "stale_or_unknown_blocks": sorted(set(stale_blocks)),
    }


def _source_chain(payload: dict[str, Any]) -> list[dict[str, Any]]:
    source_chain = payload.get("source_chain")
    if isinstance(source_chain, list):
        return [dict(item) for item in source_chain if isinstance(item, dict)]
    source = str(payload.get("source") or "")
    status = str(payload.get("status") or "")
    return [{"provider": source, "status": status}] if source else []


def _freshness_label(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "")
    freshness = payload.get("freshness")
    if isinstance(freshness, dict):
        if freshness.get("stale"):
            return "stale"
        if status != "ok":
            return "unknown"
        return "fresh"
    return "fresh" if status == "ok" else "unknown"


def _coverage_from_status(status: str) -> str:
    if status == "ok":
        return "ok"
    if status in {"empty", "missing", "provider_not_configured"}:
        return "missing"
    return "partial" if status else "unknown"


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result
