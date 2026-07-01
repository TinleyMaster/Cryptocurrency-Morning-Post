from __future__ import annotations

from typing import Any

import requests

from app.models.market import MarketSnapshot, TopCoin, TrendingNarrative


class CmcClient:
    BASE_URL = "https://pro-api.coinmarketcap.com"
    TRIAL_BASE_PATH = "/trial-pro-api"

    def __init__(
        self,
        api_key: str | None = None,
        market_config: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.market_config = market_config or {}
        self.timeout = timeout

    def get_market_snapshot(self) -> MarketSnapshot:
        global_data = self._request("/v1/global-metrics/quotes/latest")["data"]
        fear_data = self._request("/v3/fear-and-greed/latest")["data"]

        quote = global_data["quote"]["USD"]
        fear_value = fear_data.get("value")
        fear_classification = fear_data.get("value_classification", "Unknown")
        sentiment = f"{fear_classification} ({fear_value})"
        summary = (
            f"总市值 {self._format_money(quote.get('total_market_cap'))}，"
            f"24h 成交额 {self._format_money(quote.get('total_volume_24h'))}，"
            f"BTC 主导率 {global_data.get('btc_dominance', 0):.2f}%。"
        )
        return MarketSnapshot(
            total_market_cap=self._format_money(quote.get("total_market_cap")),
            btc_dominance=f"{global_data.get('btc_dominance', 0):.2f}%",
            sentiment=sentiment,
            summary=summary,
        )

    def get_trending_narratives(self) -> list[TrendingNarrative]:
        categories = self._request(
            "/v1/cryptocurrency/categories",
            params={"start": 1, "limit": 20},
        )["data"]
        sorted_categories = sorted(
            categories,
            key=lambda item: (item.get("volume") or 0, item.get("market_cap") or 0),
            reverse=True,
        )[:3]

        narratives: list[TrendingNarrative] = []
        for rank, item in enumerate(sorted_categories, start=1):
            detail = self._request(
                "/v1/cryptocurrency/category",
                params={"id": item["id"], "limit": 3},
            )["data"]
            leader_assets = [
                coin.get("symbol", "")
                for coin in detail.get("coins", [])
                if coin.get("symbol")
            ]
            narratives.append(
                TrendingNarrative(
                    name=item.get("name", f"Category {rank}"),
                    heat_rank=rank,
                    leader_assets=leader_assets[:3],
                )
            )
        return narratives

    def get_top_coins(self) -> list[TopCoin]:
        coin_ids = self.market_config.get(
            "major_coin_ids", {"BTC": 1, "ETH": 1027, "SOL": 5426, "BNB": 1839}
        )
        id_str = ",".join(str(value) for value in coin_ids.values())
        response = self._request(
            "/v3/cryptocurrency/quotes/latest",
            params={"id": id_str, "convert": "USD"},
        )["data"]

        items = response if isinstance(response, list) else list(response.values())
        top_coins: list[TopCoin] = []
        for item in items:
            quote_list = item.get("quote", [])
            quote = quote_list[0] if isinstance(quote_list, list) and quote_list else {}
            category_tag = self._pick_category_tag(item.get("tags", []))
            top_coins.append(
                TopCoin(
                    symbol=item.get("symbol", ""),
                    sector=category_tag or "主流资产",
                    price=self._format_price(quote.get("price")),
                    volume_change=self._format_percent(quote.get("volume_change_24h")),
                    reason=f"CMC 排名 #{item.get('cmc_rank', '-')}",
                )
            )
        return top_coins

    def _request(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        base_path = ""
        if self.api_key:
            headers["X-CMC_PRO_API_KEY"] = self.api_key
        else:
            base_path = self.TRIAL_BASE_PATH

        session = requests.Session()
        session.trust_env = False
        response = session.get(
            f"{self.BASE_URL}{base_path}{path}",
            headers=headers,
            params=params,
            timeout=self.timeout,
        )
        data = response.json()
        status = data.get("status", {})
        error_code = int(status.get("error_code") or 0)
        if response.status_code >= 400 or error_code != 0:
            raise RuntimeError(
                f"CMC request failed: status={response.status_code}, error_code={error_code}, "
                f"error_message={status.get('error_message')}"
            )
        return data

    @staticmethod
    def _format_money(value: float | int | None) -> str:
        if value is None:
            return "-"
        abs_value = abs(value)
        if abs_value >= 1_000_000_000_000:
            return f"${value / 1_000_000_000_000:.2f}T"
        if abs_value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if abs_value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        return f"${value:,.2f}"

    @staticmethod
    def _format_price(value: float | int | None) -> str:
        if value is None:
            return "-"
        if value >= 100:
            return f"${value:,.2f}"
        if value >= 1:
            return f"${value:,.4f}"
        return f"${value:,.6f}"

    @staticmethod
    def _format_percent(value: float | int | None) -> str:
        if value is None:
            return "-"
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.2f}%"

    @staticmethod
    def _pick_category_tag(tags: list[dict[str, Any]] | list[str]) -> str:
        if not tags:
            return ""
        if isinstance(tags[0], str):
            return str(tags[0])
        for tag in tags:
            if tag.get("category") == "CATEGORY":
                return tag.get("name", "")
        return tags[0].get("name", "")
