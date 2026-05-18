"""本地 Markdown IO 与未来语雀同步边界。"""

from __future__ import annotations

from pathlib import Path


def read_markdown(path: str | Path) -> str:
    """按 UTF-8 读取 Markdown 文件。"""

    return Path(path).read_text(encoding="utf-8")


def write_markdown(path: str | Path, content: str) -> None:
    """写入 Markdown 文本，必要时创建父目录。"""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def patch_markdown(path: str | Path, old: str, new: str) -> None:
    """替换第一个精确匹配的 Markdown 片段。

    精确匹配补丁刻意保持保守，避免宪法编辑时静默改错段落。
    """

    target = Path(path)
    content = target.read_text(encoding="utf-8")
    if old not in content:
        raise ValueError(f"Patch target not found in {target}")
    target.write_text(content.replace(old, new, 1), encoding="utf-8")


def sync_to_yuque(markdown: str, title: str) -> dict[str, str]:
    """未来语雀云同步的占位边界。"""

    return {
        "title": title,
        "status": "not_configured",
        "message": "placeholder: connect Yuque API here",
        "preview": markdown[:200],
    }
