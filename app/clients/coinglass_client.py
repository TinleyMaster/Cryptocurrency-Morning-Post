from __future__ import annotations

from typing import Any

import requests


class CoinGlassClient:
    BASE_URL = "https://open-api-v4.coinglass.com"

    def __init__(
        self,
        api_key: str | None = None,
        market_config: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.market_config = market_config or {}
        self.timeout = timeout

    def get_total_liquidations_24h(self) -> str:
        if not self.api_key:
            raise RuntimeError("COINGLASS_API_KEY 未配置")

        exchanges = self.market_config.get("coinglass", {}).get(
            "exchange_watchlist",
            ["Binance", "OKX", "Bybit"],
        )
        if not exchanges:
            raise RuntimeError("coinglass.exchange_watchlist 为空")

        total = 0.0
        success_count = 0
        last_error: Exception | None = None
        for exchange in exchanges:
            try:
                payload = self._request(
                    "/api/futures/liquidation/coin-list",
                    params={"exchange": exchange},
                )
            except Exception as exc:  # pragma: no cover - guarded by caller fallback
                last_error = exc
                continue

            rows = payload.get("data", [])
            if not isinstance(rows, list):
                continue
            total += sum(float(item.get("liquidation_usd_24h") or 0) for item in rows)
            success_count += 1

        if success_count == 0:
            raise RuntimeError(
                f"CoinGlass liquidations unavailable across exchanges: {last_error}"
            )
        return self._format_money(total)

    def _request(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        session = requests.Session()
        session.trust_env = False
        response = session.get(
            f"{self.BASE_URL}{path}",
            headers={
                "Accept": "application/json",
                "CG-API-KEY": self.api_key or "",
            },
            params=params,
            timeout=self.timeout,
        )
        data = response.json()
        code = str(data.get("code", "0"))
        if response.status_code >= 400 or code != "0":
            raise RuntimeError(
                f"CoinGlass request failed: status={response.status_code}, code={code}, message={data.get('msg')}"
            )
        return data

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
