"""Local markdown IO and future Yuque sync boundary."""

from __future__ import annotations

from pathlib import Path


def read_markdown(path: str | Path) -> str:
    """Read a markdown file as UTF-8 text."""

    return Path(path).read_text(encoding="utf-8")


def write_markdown(path: str | Path, content: str) -> None:
    """Write markdown text, creating parent directories when needed."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def patch_markdown(path: str | Path, old: str, new: str) -> None:
    """Replace the first exact markdown fragment match.

    Exact-match patching is deliberately conservative so constitution edits do
    not silently modify the wrong section.
    """

    target = Path(path)
    content = target.read_text(encoding="utf-8")
    if old not in content:
        raise ValueError(f"Patch target not found in {target}")
    target.write_text(content.replace(old, new, 1), encoding="utf-8")


def sync_to_yuque(markdown: str, title: str) -> dict[str, str]:
    """Placeholder boundary for future Yuque cloud synchronization."""

    return {
        "title": title,
        "status": "not_configured",
        "message": "placeholder: connect Yuque API here",
        "preview": markdown[:200],
    }
