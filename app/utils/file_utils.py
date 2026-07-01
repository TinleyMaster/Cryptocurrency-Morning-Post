from __future__ import annotations

from pathlib import Path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_utf8(path: Path, content: str) -> Path:
    ensure_parent(path)
    path.write_text(content, encoding="utf-8")
    return path
