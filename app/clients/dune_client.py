from __future__ import annotations

from typing import Any

import requests

from app.models.market import WhaleObservation


class DuneClient:
    BASE_URL = "https://api.dune.com/api"

    def __init__(
        self,
        api_key: str | None = None,
        market_config: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.market_config = market_config or {}
        self.timeout = timeout

    def get_whale_observations(self) -> list[WhaleObservation]:
        dune_config = self.market_config.get("dune", {})
        query_id = dune_config.get("whale_query_id")
        if not self.api_key:
            raise RuntimeError("DUNE_API_KEY 未配置")
        if not query_id:
            raise RuntimeError("market.yaml 未配置 dune.whale_query_id")

        response = self._request(
            f"/v1/query/{query_id}/results",
            params={
                "limit": dune_config.get("whale_limit", 5),
                "allow_partial_results": "true",
            },
        )
        rows = response.get("result", {}).get("rows", [])
        if not rows:
            return [
                WhaleObservation(
                    chain="-",
                    symbol="-",
                    amount_usd="-",
                    interpretation="Dune 已接通，但当前巨鲸查询没有返回结果。",
                )
            ]

        row_mapping = dune_config.get("row_mapping", {})
        observations: list[WhaleObservation] = []
        for row in rows:
            observations.append(
                WhaleObservation(
                    chain=self._get_string_value(
                        row,
                        row_mapping.get("chain", "chain"),
                        fallback_keys=("blockchain", "network"),
                        default="unknown",
                    ),
                    symbol=self._get_string_value(
                        row,
                        row_mapping.get("symbol", "symbol"),
                        fallback_keys=("asset", "token_symbol", "ticker"),
                        default="-",
                    ),
                    amount_usd=self._get_amount_value(
                        row,
                        row_mapping.get("amount_usd", "amount_usd"),
                    ),
                    interpretation=self._get_string_value(
                        row,
                        row_mapping.get("interpretation", "interpretation"),
                        fallback_keys=("summary", "note", "notes"),
                        default="检测到真实链上大额活动，需结合上下文进一步解读。",
                    ),
                )
            )
        return observations

    def _request(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        session = requests.Session()
        session.trust_env = False
        response = session.get(
            f"{self.BASE_URL}{path}",
            headers={
                "X-Dune-Api-Key": self.api_key or "",
                "Accept": "application/json",
            },
            params=params,
            timeout=self.timeout,
        )
        data = response.json()
        if response.status_code >= 400:
            raise RuntimeError(
                f"Dune request failed: status={response.status_code}, error={data}"
            )
        state = data.get("state")
        if state and state != "QUERY_STATE_COMPLETED":
            error = data.get("error", {})
            raise RuntimeError(
                f"Dune query is not ready: state={state}, error={error.get('message')}"
            )
        if data.get("error"):
            error = data["error"]
            raise RuntimeError(
                f"Dune query returned error: type={error.get('type')}, message={error.get('message')}"
            )
        return data

    @staticmethod
    def _get_string_value(
        row: dict[str, Any],
        primary_key: str,
        fallback_keys: tuple[str, ...] = (),
        default: str = "",
    ) -> str:
        for key in (primary_key, *fallback_keys):
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
        return default

    def _get_amount_value(self, row: dict[str, Any], key: str) -> str:
        value = row.get(key)
        if value in (None, ""):
            for fallback in ("usd_value", "volume_usd", "amount", "value"):
                if row.get(fallback) not in (None, ""):
                    value = row[fallback]
                    break
        if isinstance(value, (int, float)):
            return self._format_money(float(value))
        if isinstance(value, str):
            stripped = value.strip()
            try:
                return self._format_money(float(stripped))
            except ValueError:
                return stripped
        return "-"

    @staticmethod
    def _format_money(value: float) -> str:
        abs_value = abs(value)
        if abs_value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if abs_value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if abs_value >= 1_000:
            return f"${value / 1_000:.2f}K"
        return f"${value:,.2f}"
