"""Free read-only market intelligence providers.

The functions in this module never write local state. They aggregate public or
free data sources and return the same standard envelope used by Skills.
"""

from __future__ import annotations

import contextlib
import io
import json
import ssl
from datetime import date, datetime, timedelta
from typing import Any
from urllib import error, request

from src.market_data.symbol_mapper import infer_market, normalize_symbol


DEFAULT_USER_AGENT = "private-investment-butler/1.0 contact: local@example.com"
HTTP_TIMEOUT_SECONDS = 10
MAX_AKSHARE_NOTICE_DAYS = 7
MAX_AKSHARE_NOTICE_REQUESTS = 12


def fetch_company_news(
    symbol: str,
    market: str | None = None,
    *,
    query: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Fetch recent company or market news from free sources."""

    clean_query = _clean_query(symbol=symbol, query=query)
    if not clean_query:
        return _error_payload("news", "market_intel_news", "", "缺少 query 参数。")

    clean_symbol = _clean_symbol_arg(symbol, clean_query)
    clean_market = _market(market, clean_symbol)
    attempts: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []

    if clean_market == "CN":
        result = _akshare_stock_news(clean_symbol or clean_query)
        attempts.append(_attempt("akshare_stock_news_em", result))
        items.extend(result.get("items") or [])
    elif clean_market == "US":
        result = _yfinance_news(clean_symbol or clean_query)
        attempts.append(_attempt("yfinance_news", result))
        items.extend(result.get("items") or [])
    else:
        for provider_name, provider in (
            ("akshare_stock_news_em", _akshare_stock_news),
            ("yfinance_news", _yfinance_news),
        ):
            result = provider(clean_symbol or clean_query)
            attempts.append(_attempt(provider_name, result))
            items.extend(result.get("items") or [])
            if items:
                break

    return _standard_intel_payload(
        data_type="news",
        source="market_intel_news",
        query=clean_query,
        symbol=clean_symbol,
        market=clean_market,
        items=_dedupe_items(items)[: _bounded_limit(limit)],
        attempts=attempts,
        empty_error="免费新闻源没有返回可用条目。",
    )


def fetch_company_announcements(
    symbol: str,
    market: str | None = None,
    *,
    query: str | None = None,
    limit: int = 10,
    days: int = 14,
) -> dict[str, Any]:
    """Fetch announcements or filings from free sources."""

    clean_query = _clean_query(symbol=symbol, query=query)
    if not clean_query:
        return _error_payload("announcement", "market_intel_announcements", "", "缺少 query 参数。")

    return _fetch_formal_disclosures(
        symbol=symbol,
        market=market,
        query=clean_query,
        limit=limit,
        days=days,
        data_type="announcement",
        source="market_intel_announcements",
        empty_error="免费公告/filings 源没有返回可用条目。",
    )


def fetch_filings(
    symbol: str,
    market: str | None = None,
    *,
    query: str | None = None,
    limit: int = 10,
    days: int = 120,
) -> dict[str, Any]:
    """Fetch formal filings and disclosure documents for a company."""

    clean_query = _clean_query(symbol=symbol, query=query)
    if not clean_query:
        return _error_payload("filing", "market_intel_filings", "", "缺少 symbol 或 query 参数。")

    return _fetch_formal_disclosures(
        symbol=symbol,
        market=market,
        query=clean_query,
        limit=limit,
        days=days,
        data_type="filing",
        source="market_intel_filings",
        empty_error="免费正式披露源没有返回可用条目。",
    )


def fetch_market_event_context(query: str, *, limit: int = 10, days: int = 14) -> dict[str, Any]:
    """Fetch a combined news and formal-disclosure context for a market query."""

    clean_query = str(query or "").strip()
    if not clean_query:
        return _error_payload("market_event_context", "market_intel_context", "", "缺少 query 参数。")

    symbol = _symbol_from_query(clean_query)
    market = _market(None, symbol)
    news = fetch_company_news(symbol or clean_query, market=market, query=clean_query, limit=limit)
    announcements = fetch_company_announcements(
        symbol or clean_query,
        market=market,
        query=clean_query,
        limit=limit,
        days=days,
    )
    news_items = _items_from_payload(news)
    announcement_items = _items_from_payload(announcements)
    attempts = _prefixed_attempts("news", news.get("source_chain")) + _prefixed_attempts(
        "announcement",
        announcements.get("source_chain"),
    )
    coverage = {
        "news": _coverage_value(news, "news"),
        "announcement": _coverage_value(announcements, "announcement"),
    }
    error_text = "；".join(
        item
        for item in [str(news.get("error") or ""), str(announcements.get("error") or "")]
        if item
    )
    status = "ok" if news_items or announcement_items else _combined_status([news, announcements])
    return {
        "status": status,
        "source": "market_intel_context",
        "data_type": "market_event_context",
        "data": {
            "query": clean_query,
            "symbol": symbol,
            "market": market,
            "news": news_items,
            "announcements": announcement_items,
        },
        "freshness": {
            "as_of": datetime.now().replace(microsecond=0).isoformat(),
            "stale": False,
            "stale_reason": "",
        },
        "warnings": [],
        "error": "" if news_items or announcement_items else error_text,
        "source_chain": attempts,
        "data_quality": {
            "source_chain": attempts,
            "freshness": "fresh" if news_items or announcement_items else "unknown",
            "coverage": coverage,
            "limitations": _dedupe_text([error_text] if error_text else []),
        },
    }


def _fetch_formal_disclosures(
    *,
    symbol: str,
    market: str | None,
    query: str,
    limit: int,
    days: int,
    data_type: str,
    source: str,
    empty_error: str,
) -> dict[str, Any]:
    clean_symbol = _clean_symbol_arg(symbol, query)
    clean_market = _market(market, clean_symbol)
    attempts: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []

    if clean_market == "CN":
        result = _akshare_stock_notices(query=query, symbol=clean_symbol, days=_bounded_days(days))
        attempts.append(_attempt("akshare_stock_notice_report", result))
        items.extend(result.get("items") or [])
    elif clean_market == "US":
        result = _sec_company_filings(clean_symbol or query)
        attempts.append(_attempt("sec_company_submissions", result))
        items.extend(result.get("items") or [])
    else:
        for provider_name, provider in (
            (
                "akshare_stock_notice_report",
                lambda value: _akshare_stock_notices(query=query, symbol=value, days=_bounded_days(days)),
            ),
            ("sec_company_submissions", _sec_company_filings),
        ):
            result = provider(clean_symbol or query)
            attempts.append(_attempt(provider_name, result))
            items.extend(result.get("items") or [])
            if items:
                break

    return _standard_intel_payload(
        data_type=data_type,
        source=source,
        query=query,
        symbol=clean_symbol,
        market=clean_market,
        items=_dedupe_items(items)[: _bounded_limit(limit)],
        attempts=attempts,
        empty_error=empty_error,
    )


def _akshare_stock_news(symbol_or_query: str) -> dict[str, Any]:
    try:
        import akshare as ak  # type: ignore
    except ModuleNotFoundError:
        return {
            "status": "provider_not_configured",
            "items": [],
            "error": "缺少 akshare，未执行 A 股东方财富新闻源。请安装 requirements.txt。",
        }

    try:
        frame = ak.stock_news_em(symbol=_clean_cn_symbol(symbol_or_query))
    except Exception as exc:
        return {"status": "error", "items": [], "error": f"AkShare 个股新闻获取失败：{exc}"}

    items: list[dict[str, Any]] = []
    for row in _frame_records(frame):
        items.append(
            {
                "title": _pick(row, "新闻标题", "title"),
                "summary": _pick(row, "新闻内容", "summary"),
                "published_at": _pick(row, "发布时间", "publish_time", "date"),
                "source": _pick(row, "文章来源", "source") or "东方财富",
                "url": _pick(row, "新闻链接", "url"),
                "provider": "akshare_stock_news_em",
            }
        )
    return {"status": "ok" if items else "empty", "items": items, "error": "" if items else "AkShare 新闻源无结果。"}


def _akshare_stock_notices(*, query: str, symbol: str, days: int) -> dict[str, Any]:
    try:
        import akshare as ak  # type: ignore
    except ModuleNotFoundError:
        return {
            "status": "provider_not_configured",
            "items": [],
            "error": "缺少 akshare，未执行 A 股东方财富公告源。请安装 requirements.txt。",
        }

    categories = _notice_categories(query)
    identity_tokens = _identity_tokens(query, symbol)
    tokens = _filter_tokens(query, symbol)
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    request_count = 0
    for day in _recent_dates(min(days, MAX_AKSHARE_NOTICE_DAYS)):
        for category in categories:
            if request_count >= MAX_AKSHARE_NOTICE_REQUESTS:
                break
            request_count += 1
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    frame = ak.stock_notice_report(symbol=category, date=day)
            except Exception as exc:
                errors.append(f"{category}/{day}: {exc}")
                continue
            for row in _frame_records(frame):
                text = " ".join(_pick(row, key) for key in ("代码", "名称", "公告标题", "公告类型"))
                if identity_tokens and not any(token in text for token in identity_tokens):
                    continue
                if not identity_tokens and tokens and not any(token in text for token in tokens):
                    continue
                items.append(
                    {
                        "symbol": _pick(row, "代码", "symbol"),
                        "name": _pick(row, "名称", "name"),
                        "title": _pick(row, "公告标题", "title"),
                        "category": _pick(row, "公告类型", "type") or category,
                        "published_at": _pick(row, "公告日期", "date"),
                        "url": _pick(row, "网址", "url"),
                        "source": "东方财富公告",
                        "provider": "akshare_stock_notice_report",
                    }
                )
        if request_count >= MAX_AKSHARE_NOTICE_REQUESTS:
            break
    if items:
        return {"status": "ok", "items": items, "error": ""}
    error_text = "；".join(errors[:3])
    return {
        "status": "empty" if not errors else "error",
        "items": [],
        "error": error_text or f"AkShare 公告源无结果（已扫描 {request_count} 次）。",
    }


def _yfinance_news(symbol_or_query: str) -> dict[str, Any]:
    try:
        import yfinance as yf  # type: ignore
    except ModuleNotFoundError:
        return {"status": "provider_not_configured", "items": [], "error": "缺少 yfinance，未执行美股新闻源。"}

    symbol = _clean_us_symbol(symbol_or_query)
    try:
        raw_items = yf.Ticker(symbol).news or []
    except Exception as exc:
        return {"status": "error", "items": [], "error": f"YFinance 新闻获取失败：{exc}"}

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        content = raw.get("content") if isinstance(raw.get("content"), dict) else raw
        published = content.get("pubDate") or content.get("displayTime") or raw.get("providerPublishTime")
        items.append(
            {
                "title": content.get("title") or raw.get("title"),
                "summary": content.get("summary") or raw.get("summary"),
                "published_at": str(published or ""),
                "source": (content.get("provider") or {}).get("displayName") if isinstance(content.get("provider"), dict) else raw.get("publisher"),
                "url": (content.get("clickThroughUrl") or {}).get("url") if isinstance(content.get("clickThroughUrl"), dict) else raw.get("link"),
                "provider": "yfinance_news",
            }
        )
    return {"status": "ok" if items else "empty", "items": items, "error": "" if items else "YFinance 新闻源无结果。"}


def _sec_company_filings(symbol_or_query: str) -> dict[str, Any]:
    symbol = _clean_us_symbol(symbol_or_query)
    try:
        cik = _sec_cik_for_symbol(symbol)
        if not cik:
            return {"status": "empty", "items": [], "error": f"SEC ticker map 未找到 {symbol}。"}
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        raw = _http_json(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    except error.HTTPError as exc:
        return {"status": "error", "items": [], "error": f"SEC filings HTTP {exc.code}。"}
    except Exception as exc:
        return {"status": "error", "items": [], "error": f"SEC filings 获取失败：{exc}"}

    recent = ((raw.get("filings") or {}).get("recent") or {}) if isinstance(raw, dict) else {}
    forms = recent.get("form") or []
    accession_numbers = recent.get("accessionNumber") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    primary_docs = recent.get("primaryDocument") or []
    items: list[dict[str, Any]] = []
    for index, form in enumerate(forms[:20]):
        accession = str(accession_numbers[index] if index < len(accession_numbers) else "")
        document = str(primary_docs[index] if index < len(primary_docs) else "")
        filing_date = str(filing_dates[index] if index < len(filing_dates) else "")
        report_date = str(report_dates[index] if index < len(report_dates) else "")
        items.append(
            {
                "symbol": symbol,
                "title": f"SEC {form}",
                "category": str(form),
                "published_at": filing_date,
                "report_date": report_date,
                "url": _sec_filing_url(cik, accession, document),
                "source": "SEC EDGAR",
                "provider": "sec_company_submissions",
            }
        )
    return {"status": "ok" if items else "empty", "items": items, "error": "" if items else "SEC filings 无近期记录。"}


def _sec_cik_for_symbol(symbol: str) -> str:
    raw = _http_json("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": DEFAULT_USER_AGENT})
    for item in raw.values():
        if str(item.get("ticker") or "").upper() == symbol.upper():
            return str(item.get("cik_str") or "").zfill(10)
    return ""


def _sec_filing_url(cik: str, accession: str, document: str) -> str:
    if not cik or not accession or not document:
        return ""
    accession_path = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{document}"


def _http_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = request.Request(url, headers=headers or {})
    with request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS, context=_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _standard_intel_payload(
    *,
    data_type: str,
    source: str,
    query: str,
    symbol: str,
    market: str,
    items: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    empty_error: str,
) -> dict[str, Any]:
    if items:
        status = "ok"
        error_text = ""
    elif attempts and all(item.get("status") == "provider_not_configured" for item in attempts):
        status = "provider_not_configured"
        error_text = "；".join(str(item.get("error") or "") for item in attempts if item.get("error"))
    elif attempts and any(item.get("status") == "error" for item in attempts):
        status = "error"
        error_text = "；".join(str(item.get("error") or "") for item in attempts if item.get("error")) or empty_error
    else:
        status = "empty"
        error_text = empty_error
    return {
        "status": status,
        "source": source,
        "data_type": data_type,
        "data": {
            "query": query,
            "symbol": symbol,
            "market": market,
            "items": items,
        },
        "freshness": {
            "as_of": datetime.now().replace(microsecond=0).isoformat(),
            "stale": False,
            "stale_reason": "",
        },
        "warnings": [],
        "error": error_text,
        "source_chain": attempts,
        "data_quality": {
            "source_chain": attempts,
            "freshness": "fresh" if items else "unknown",
            "coverage": {data_type: _coverage_from_items(items, attempts)},
            "limitations": [error_text] if error_text else [],
        },
    }


def _error_payload(data_type: str, source: str, query: str, error_text: str) -> dict[str, Any]:
    return _standard_intel_payload(
        data_type=data_type,
        source=source,
        query=query,
        symbol="",
        market="",
        items=[],
        attempts=[{"provider": source, "status": "error", "error": error_text}],
        empty_error=error_text,
    )


def _clean_query(*, symbol: str, query: str | None) -> str:
    clean_query = str(query or "").strip()
    if clean_query:
        return clean_query
    return str(symbol or "").strip()


def _clean_symbol_arg(symbol: str, query: str) -> str:
    explicit = str(symbol or "").strip().upper()
    if explicit and (" " not in explicit) and ("，" not in explicit) and ("," not in explicit):
        return explicit
    return _symbol_from_query(query)


def _symbol_from_query(query: str) -> str:
    for token in query.replace("，", " ").replace(",", " ").split():
        clean = token.strip().strip("()（）[]【】").upper()
        if clean.isdigit() and len(clean) == 6:
            return clean
    return ""


def _market(market: str | None, symbol: str) -> str:
    explicit = str(market or "").strip().upper()
    if explicit:
        return "CN" if explicit in {"A", "ASHARE", "A_SHARE"} else explicit
    return infer_market(symbol) if symbol else ""


def _bounded_limit(value: int) -> int:
    try:
        return max(1, min(int(value or 10), 20))
    except (TypeError, ValueError):
        return 10


def _bounded_days(value: int) -> int:
    try:
        return max(1, min(int(value or 14), 365))
    except (TypeError, ValueError):
        return 14


def _items_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    items = data.get("items")
    return [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _prefixed_attempts(data_type: str, attempts: Any) -> list[dict[str, Any]]:
    if not isinstance(attempts, list):
        return []
    result: list[dict[str, Any]] = []
    for item in attempts:
        if not isinstance(item, dict):
            continue
        clean = dict(item)
        clean["data_type"] = data_type
        result.append(clean)
    return result


def _coverage_value(payload: dict[str, Any], data_type: str) -> str:
    quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {}
    coverage = quality.get("coverage") if isinstance(quality.get("coverage"), dict) else {}
    return str(coverage.get(data_type) or "missing")


def _coverage_from_items(items: list[dict[str, Any]], attempts: list[dict[str, Any]]) -> str:
    if not items:
        return "missing"
    failed_attempts = [
        item
        for item in attempts
        if str(item.get("status") or "") not in {"", "ok"}
    ]
    return "partial" if failed_attempts else "ok"


def _combined_status(payloads: list[dict[str, Any]]) -> str:
    statuses = [str(item.get("status") or "") for item in payloads]
    if statuses and all(status == "provider_not_configured" for status in statuses):
        return "provider_not_configured"
    if any(status == "error" for status in statuses):
        return "error"
    if any(status == "empty" for status in statuses):
        return "empty"
    return "missing"


def _clean_cn_symbol(symbol: str) -> str:
    clean = normalize_symbol(symbol)
    for suffix in (".SH", ".SS", ".SZ"):
        if clean.endswith(suffix):
            return clean[: -len(suffix)]
    return clean


def _clean_us_symbol(symbol: str) -> str:
    clean = normalize_symbol(symbol)
    for suffix in (".US", ".NASDAQ", ".NYSE", ".AMEX"):
        if clean.endswith(suffix):
            return clean[: -len(suffix)]
    return clean


def _notice_categories(query: str) -> list[str]:
    text = query.lower()
    if any(token in text for token in ["财报", "年报", "季报", "业绩", "利润"]):
        return ["财务报告", "重大事项"]
    if any(token in text for token in ["风险", "诉讼", "处罚", "担保"]):
        return ["风险提示", "重大事项"]
    if any(token in text for token in ["减持", "增持", "持股"]):
        return ["持股变动", "重大事项"]
    if any(token in text for token in ["重组", "并购", "资产"]):
        return ["资产重组", "重大事项"]
    return ["全部", "重大事项", "财务报告"]


def _filter_tokens(query: str, symbol: str) -> list[str]:
    tokens = []
    clean_symbol = _clean_cn_symbol(symbol)
    if clean_symbol:
        tokens.append(clean_symbol)
    for token in query.replace("，", " ").replace(",", " ").split():
        clean = token.strip().strip("()（）[]【】")
        if len(clean) >= 2 and not clean.lower() in {"最新", "新闻", "公告", "财报", "风险"}:
            tokens.append(clean)
    return _dedupe_text(tokens)


def _identity_tokens(query: str, symbol: str) -> list[str]:
    tokens = []
    clean_symbol = _clean_cn_symbol(symbol)
    if clean_symbol:
        tokens.append(clean_symbol)
    generic = {
        "最新",
        "新闻",
        "公告",
        "财报",
        "风险",
        "分红",
        "利润分配",
        "权益分派",
        "实施公告",
        "年报",
        "半年报",
        "季报",
    }
    for token in query.replace("，", " ").replace(",", " ").split():
        clean = token.strip().strip("()（）[]【】")
        if clean.isdigit() and len(clean) == 6:
            tokens.append(clean)
        elif len(clean) >= 3 and clean not in generic and not clean.lower().isascii():
            tokens.append(clean)
    return _dedupe_text(tokens)


def _recent_dates(days: int) -> list[str]:
    today = date.today()
    return [(today - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days)]


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if hasattr(frame, "to_dict"):
        return [dict(item) for item in frame.to_dict(orient="records")]
    return []


def _pick(row: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _attempt(provider: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": result.get("status") or "missing",
        "error": result.get("error") or "",
    }


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        key = (title, url)
        if not title or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_text(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result
