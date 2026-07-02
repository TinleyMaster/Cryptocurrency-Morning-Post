from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_FILE = PROJECT_ROOT / ".env"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _extract_feishu_token(value: str | None, resource: str) -> str | None:
    if not value:
        return value
    value = value.strip()
    if not value:
        return value
    if "://" not in value:
        return value

    parsed = urlparse(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query)

    if resource == "folder" and "folder" in path_parts:
        index = path_parts.index("folder")
        if index + 1 < len(path_parts):
            return path_parts[index + 1]
    if resource == "base" and "base" in path_parts:
        index = path_parts.index("base")
        if index + 1 < len(path_parts):
            return path_parts[index + 1]
    if resource == "table":
        table = query.get("table", [])
        if table:
            return table[0]
    return value


def _merge_feishu_config(
    feishu: dict[str, Any], env: dict[str, str | None]
) -> dict[str, Any]:
    merged = dict(feishu)
    overrides = {
        "folder_token": _extract_feishu_token(env.get("FEISHU_FOLDER_TOKEN"), "folder"),
        "chat_id": env.get("FEISHU_CHAT_ID"),
        "base_token": _extract_feishu_token(env.get("FEISHU_BASE_TOKEN"), "base"),
        "table_id": _extract_feishu_token(env.get("FEISHU_TABLE_ID"), "table"),
        "webhook_url": env.get("FEISHU_WEBHOOK_URL"),
    }
    for key, value in overrides.items():
        if value:
            merged[key] = value
    return merged


@dataclass
class Settings:
    runtime: dict[str, Any]
    market: dict[str, Any]
    feishu: dict[str, Any]
    kols: dict[str, Any]
    env: dict[str, str | None]

    @property
    def timezone(self) -> str:
        return self.runtime.get("timezone", "Asia/Shanghai")

    @property
    def output_dirs(self) -> dict[str, Path]:
        output = self.runtime.get("output", {})
        return {key: PROJECT_ROOT / value for key, value in output.items()}


def load_settings() -> Settings:
    _load_dotenv(ENV_FILE)
    env = {
        "CMC_API_KEY": os.getenv("CMC_API_KEY"),
        "COINGLASS_API_KEY": os.getenv("COINGLASS_API_KEY"),
        "DWELLIR_API_KEY": os.getenv("DWELLIR_API_KEY"),
        "HELIUS_API_KEY": os.getenv("HELIUS_API_KEY"),
        "QUICKNODE_SOLANA_RPC_URL": os.getenv("QUICKNODE_SOLANA_RPC_URL"),
        "WECOM_BOT_WEBHOOK_URL": os.getenv("WECOM_BOT_WEBHOOK_URL"),
        "XPOZ_API_KEY": os.getenv("XPOZ_API_KEY"),
        "DUNE_API_KEY": os.getenv("DUNE_API_KEY"),
        "FEISHU_APP_ID": os.getenv("FEISHU_APP_ID"),
        "FEISHU_APP_SECRET": os.getenv("FEISHU_APP_SECRET"),
        "FEISHU_FOLDER_TOKEN": os.getenv("FEISHU_FOLDER_TOKEN"),
        "FEISHU_CHAT_ID": os.getenv("FEISHU_CHAT_ID"),
        "FEISHU_BASE_TOKEN": os.getenv("FEISHU_BASE_TOKEN"),
        "FEISHU_TABLE_ID": os.getenv("FEISHU_TABLE_ID"),
        "FEISHU_WEBHOOK_URL": os.getenv("FEISHU_WEBHOOK_URL"),
    }
    feishu = _merge_feishu_config(_read_yaml(CONFIG_DIR / "feishu.yaml"), env)
    return Settings(
        runtime=_read_yaml(CONFIG_DIR / "runtime.yaml"),
        market=_read_yaml(CONFIG_DIR / "market.yaml"),
        feishu=feishu,
        kols=_read_yaml(CONFIG_DIR / "kols.yaml"),
        env=env,
    )
