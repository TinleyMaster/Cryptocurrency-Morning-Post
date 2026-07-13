from __future__ import annotations

from typing import Any

import requests

from app.models.market import DwellirHyperliquidMarket, DwellirHyperliquidMonitor


class DwellirClient:
    HYPERLIQUID_INFO_URL = "https://api-hyperliquid-mainnet-info.n.dwellir.com/info"
    HYPERLIQUID_PUBLIC_INFO_URL = "https://api.hyperliquid.xyz/info"

    def __init__(
        self,
        api_key: str | None = None,
        market_config: dict[str, Any] | None = None,
        timeout: int = 20,
    ) -> None:
        self.api_key = api_key
        self.market_config = market_config or {}
        self.timeout = timeout

    def get_hyperliquid_market_monitor(self) -> DwellirHyperliquidMonitor:
        self._ensure_api_key()
        config = self.market_config.get("dwellir", {}).get("hyperliquid", {})
        symbols = [
            str(item).upper() for item in config.get("symbols", ["BTC", "ETH", "SOL"])
        ]
        fallback_notes: list[str] = []
        meta_payload, meta_note = self._request_info({"type": "metaAndAssetCtxs"})
        if meta_note:
            fallback_notes.append(meta_note)
        mids, mids_note = self._request_info({"type": "allMids"})
        if mids_note and mids_note not in fallback_notes:
            fallback_notes.append(mids_note)
        meta, asset_contexts = self._unpack_meta_payload(meta_payload)
        universe = meta.get("universe", [])

        rows: list[dict[str, Any]] = []
        missing_symbols: list[str] = []
        for symbol in symbols:
            row = self._build_market_row(symbol, universe, asset_contexts, mids)
            if row is None:
                missing_symbols.append(symbol)
                continue
            rows.append(row)

        if not rows:
            missing = (
                ", ".join(missing_symbols) if missing_symbols else ", ".join(symbols)
            )
            raise RuntimeError(f"Dwellir 未返回可用的 Hyperliquid 市场数据：{missing}")

        total_volume = sum(float(item["volume_24h"]) for item in rows)
        positive_count = sum(1 for item in rows if float(item["change_pct"]) > 0)
        hottest = max(rows, key=lambda item: float(item["volume_24h"]))
        funding_focus = max(rows, key=lambda item: abs(float(item["funding_rate_raw"])))
        funding_tone = self._build_funding_tone(funding_focus)
        breadth = f"上涨 {positive_count}/{len(rows)}"
        summary = (
            f"{hottest['symbol']} 24h 名义成交量最活跃，"
            f"监控池总成交额 {self._format_money(total_volume)}，"
            f"{breadth}，{funding_tone}。"
        )
        if missing_symbols:
            summary += f" 未命中币种：{', '.join(missing_symbols)}。"
        if fallback_notes:
            summary += f" {' '.join(fallback_notes)}"

        markets = [
            DwellirHyperliquidMarket(
                symbol=item["symbol"],
                price=self._format_price(float(item["price"])),
                change_24h=self._format_percent(float(item["change_pct"])),
                volume_24h=self._format_money(float(item["volume_24h"])),
                funding_rate=self._format_percent(
                    float(item["funding_rate_raw"]) * 100
                ),
                open_interest=self._format_money(float(item["open_interest_usd"])),
                signal=item["signal"],
            )
            for item in rows
        ]

        return DwellirHyperliquidMonitor(
            watchlist=" / ".join(symbols),
            total_volume_24h=self._format_money(total_volume),
            breadth=breadth,
            funding_tone=funding_tone,
            hottest_market=(
                f"{hottest['symbol']} | 价格 {self._format_price(float(hottest['price']))} | "
                f"24h 成交 {self._format_money(float(hottest['volume_24h']))}"
            ),
            markets=markets,
            summary=summary,
        )

    def _build_market_row(
        self,
        symbol: str,
        universe: list[dict[str, Any]],
        asset_contexts: list[dict[str, Any]],
        mids: dict[str, Any],
    ) -> dict[str, Any] | None:
        index = next(
            (
                i
                for i, item in enumerate(universe)
                if str(item.get("name", "")).upper() == symbol
            ),
            None,
        )
        if index is None or index >= len(asset_contexts):
            return None

        context = asset_contexts[index]
        price = self._to_float(
            mids.get(symbol) or context.get("midPx") or context.get("markPx")
        )
        prev_day_price = self._to_float(context.get("prevDayPx"))
        change_pct = (
            ((price - prev_day_price) / prev_day_price * 100) if prev_day_price else 0.0
        )
        volume_24h = self._to_float(context.get("dayNtlVlm"))
        funding_rate = self._to_float(context.get("funding"))
        open_interest_base = self._to_float(context.get("openInterest"))
        open_interest_usd = open_interest_base * price
        return {
            "symbol": symbol,
            "price": price,
            "change_pct": change_pct,
            "volume_24h": volume_24h,
            "funding_rate_raw": funding_rate,
            "open_interest_usd": open_interest_usd,
            "signal": self._classify_signal(change_pct, funding_rate, volume_24h),
        }

    def _request_info(self, payload: dict[str, Any]) -> tuple[Any, str]:
        try:
            return self._post_info(
                self.HYPERLIQUID_INFO_URL,
                payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Api-Key": self.api_key or "",
                },
            ), ""
        except RuntimeError as exc:
            if not self._should_fallback_to_public(exc):
                raise
            fallback_note = (
                "Dwellir Info Endpoint rejected this request type; "
                "automatically fell back to the official Hyperliquid endpoint."
            )
            return (
                self._post_info(
                    self.HYPERLIQUID_PUBLIC_INFO_URL,
                    payload,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                ),
                fallback_note,
            )

    def _post_info(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        session = requests.Session()
        session.trust_env = False
        response = session.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        try:
            data = response.json()
        except ValueError as exc:
            text_head = response.text[:300]
            raise RuntimeError(
                f"Dwellir request returned non-JSON response: status={response.status_code}, "
                f"url={url}, payload={payload}, body={text_head!r}"
            ) from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"Dwellir request failed: status={response.status_code}, url={url}, "
                f"payload={payload}, body={data}"
            )
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Dwellir request failed: {data['error']}")
        return data

    @staticmethod
    def _should_fallback_to_public(exc: RuntimeError) -> bool:
        message = str(exc)
        return (
            "status=422" in message
            or "status=403" in message
            and "type not allowed" in message
            or "Failed to deserialize the JSON body into the target type" in message
            or "non-JSON response" in message
            or "type not allowed" in message
        )

    @staticmethod
    def _unpack_meta_payload(
        payload: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not isinstance(payload, list) or len(payload) != 2:
            raise RuntimeError(
                f"Unexpected Dwellir metaAndAssetCtxs response: {payload}"
            )
        meta = payload[0] if isinstance(payload[0], dict) else {}
        asset_contexts = payload[1] if isinstance(payload[1], list) else []
        return meta, asset_contexts

    def _ensure_api_key(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "DWELLIR_API_KEY 未配置，无法获取 Hyperliquid 市场温度。"
            )

    @staticmethod
    def _classify_signal(
        change_pct: float, funding_rate: float, volume_24h: float
    ) -> str:
        if change_pct >= 3 and funding_rate > 0.0001:
            return "偏多升温"
        if change_pct <= -3 and funding_rate < -0.0001:
            return "偏空升温"
        if volume_24h >= 1_000_000_000:
            return "高流动性"
        if abs(funding_rate) >= 0.0002:
            return "杠杆活跃"
        return "中性"

    @staticmethod
    def _build_funding_tone(funding_focus: dict[str, Any]) -> str:
        rate = float(funding_focus["funding_rate_raw"])
        symbol = str(funding_focus["symbol"])
        if abs(rate) < 0.00005:
            return "资金费率整体平静"
        if rate > 0:
            return f"{symbol} 资金费率最热，短线偏多拥挤"
        return f"{symbol} 资金费率最冷，短线偏空拥挤"

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _format_money(value: float) -> str:
        abs_value = abs(value)
        if abs_value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        if abs_value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if abs_value >= 1_000:
            return f"{value / 1_000:.2f}K"
        return f"{value:.2f}"

    @staticmethod
    def _format_percent(value: float) -> str:
        return f"{value:+.2f}%"

    @staticmethod
    def _format_price(value: float) -> str:
        if value >= 1000:
            return f"{value:,.2f}"
        if value >= 1:
            return f"{value:,.3f}"
        return f"{value:,.6f}"
