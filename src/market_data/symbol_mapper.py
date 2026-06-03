from __future__ import annotations


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def infer_market(symbol: str) -> str:
    clean = normalize_symbol(symbol)
    if clean.endswith((".SH", ".SS", ".SZ")) or (clean.isdigit() and len(clean) == 6):
        return "CN"
    if clean.endswith((".US", ".NASDAQ", ".NYSE", ".AMEX")):
        return "US"
    return "US" if any(ch.isalpha() for ch in clean) else "CN"


def to_yahoo_symbol(symbol: str) -> str:
    """Map A-share symbols to Yahoo Finance symbols."""

    clean = normalize_symbol(symbol)
    if clean.endswith(".SS"):
        return clean
    if clean.endswith(".SH"):
        return clean[:-3] + ".SS"
    if clean.endswith(".SZ"):
        return clean
    if clean.isdigit() and len(clean) == 6:
        suffix = ".SS" if clean.startswith(("5", "6", "9")) else ".SZ"
        return clean + suffix
    return clean


def to_longbridge_symbol(symbol: str) -> str:
    clean = normalize_symbol(symbol)
    if clean.endswith(".US"):
        return clean
    if "." not in clean:
        return clean + ".US"
    return clean
