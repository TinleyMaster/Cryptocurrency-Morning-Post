from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests

from app.models.market import (
    DefiLlamaCategoryFlow,
    DefiLlamaChainFlow,
    DefiLlamaMonitor,
    DefiLlamaOverview,
    DefiLlamaPegRisk,
    DefiLlamaProtocol,
)


class DefiLlamaClient:
    BASE_URL = "https://api.llama.fi"
    STABLECOIN_BASE_URL = "https://stablecoins.llama.fi"
    BRIDGES_BASE_URL = "https://bridges.llama.fi"
    TRUE_FLOW_24H_UNAVAILABLE = "需 DefiLlama Pro inflows"
    BRIDGE_NOTE_PAID = "跨链桥 24h 净流量需 DefiLlama Paid API"
    LIQUIDATION_NOTE_KEY = "24h 清算总额需配置 COINGLASS_API_KEY"

    def __init__(
        self,
        market_config: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> None:
        self.market_config = market_config or {}
        self.timeout = timeout

    def get_monitor_snapshot(self) -> DefiLlamaMonitor:
        total_history = self._request_list(f"{self.BASE_URL}/v2/historicalChainTvl")
        if len(total_history) < 2:
            raise RuntimeError(
                "DefiLlama historicalChainTvl returned insufficient data"
            )

        protocols = self._request_list(f"{self.BASE_URL}/protocols")
        chains = self._request_list(f"{self.BASE_URL}/v2/chains")
        stablecoins_payload = self._request_dict(
            f"{self.STABLECOIN_BASE_URL}/stablecoins"
        )
        dexs_overview = self._request_dict(
            f"{self.BASE_URL}/overview/dexs"
            "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
        )

        overview = self._build_overview(
            total_history,
            stablecoins_payload,
            dexs_overview,
        )
        chain_rows = self._build_chain_rows(chains)
        category_rows = self._build_category_rows(protocols)
        peg_risks = self._build_peg_risks(stablecoins_payload)
        top_protocols = self._build_top_protocols(protocols)

        return DefiLlamaMonitor(
            overview=overview,
            chain_summary=self._build_chain_summary(chain_rows),
            category_summary=self._build_category_summary(category_rows),
            chain_flows=[
                DefiLlamaChainFlow(
                    name=item["name"],
                    tvl=self._format_money(item["tvl"]),
                    change_7d=self._format_percent(item["change_7d"]),
                    change_amount_7d=self._format_signed_money(
                        item["change_7d_amount"]
                    ),
                    bridge_netflow_24h=self._format_optional_signed_money(
                        item.get("bridge_netflow_24h")
                    ),
                    signal=item["signal"],
                )
                for item in chain_rows
            ],
            category_flows=[
                DefiLlamaCategoryFlow(
                    name=item["display_name"],
                    tvl=self._format_money(item["tvl"]),
                    change_7d=self._format_percent(item["change_7d"]),
                    netflow_7d=self._format_signed_money(item["netflow_7d"]),
                    signal=item["signal"],
                )
                for item in category_rows
            ],
            peg_summary=self._build_peg_summary(peg_risks),
            peg_risks=peg_risks,
            protocol_summary=self._build_protocol_summary(top_protocols),
            top_protocols=top_protocols,
        )

    def _build_overview(
        self,
        total_history: list[dict[str, Any]],
        stablecoins_payload: dict[str, Any],
        dexs_overview: dict[str, Any],
    ) -> DefiLlamaOverview:
        current_tvl = float(total_history[-1].get("tvl") or 0)
        change_1d = self._compute_change_amount_from_history(total_history, days=1)
        change_7d = self._compute_change_amount_from_history(total_history, days=7)

        stablecoins = stablecoins_payload.get("peggedAssets", [])
        usd_assets = [
            item
            for item in stablecoins
            if isinstance(item, dict) and item.get("pegType") == "peggedUSD"
        ]
        stablecoin_mcap = sum(
            float((item.get("circulating") or {}).get("peggedUSD") or 0)
            for item in usd_assets
        )
        stablecoin_prev_week = sum(
            float((item.get("circulatingPrevWeek") or {}).get("peggedUSD") or 0)
            for item in usd_assets
        )
        stablecoin_prev_day = sum(
            float((item.get("circulatingPrevDay") or {}).get("peggedUSD") or 0)
            for item in usd_assets
        )
        stablecoin_change_7d = self._compute_change_from_values(
            current=stablecoin_mcap,
            baseline=stablecoin_prev_week,
        )
        stablecoin_supply_change_1d = stablecoin_mcap - stablecoin_prev_day

        usdt = next(
            (item for item in usd_assets if item.get("symbol") == "USDT"),
            None,
        )
        usdt_supply = float((usdt or {}).get("circulating", {}).get("peggedUSD") or 0)
        usdt_dominance = usdt_supply / stablecoin_mcap * 100 if stablecoin_mcap else 0.0

        dex_volume_24h = float(dexs_overview.get("total24h") or 0)
        dex_volume_change_7d = float(dexs_overview.get("change_7d") or 0)
        bridge_netflow_24h = self._get_bridge_netflow_24h("all")
        true_flow_24h = self.TRUE_FLOW_24H_UNAVAILABLE
        bridge_note = "" if bridge_netflow_24h is not None else self.BRIDGE_NOTE_PAID
        liquidation_24h = "待配置官方 API"
        liquidation_note = self.LIQUIDATION_NOTE_KEY
        risk_signal = self._build_overview_risk_signal(
            stablecoin_supply_change_1d=stablecoin_supply_change_1d,
            tvl_change_1d=change_1d,
            dex_volume_change_7d=dex_volume_change_7d,
        )
        attribution_note = (
            "TVL 1d/7d 变化包含币价波动；若需拆分真实资金流入/流出与 Price Drop，"
            "需要 DefiLlama Pro inflows。"
        )
        summary = (
            f"稳定币总市值 {self._format_money(stablecoin_mcap)}，"
            f"全网 TVL 24h 变化 {self._format_signed_money(change_1d)}，"
            f"DEX 24h 交易量 {self._format_money(dex_volume_24h)}，"
            f"风险判断：{risk_signal}。"
        )
        if bridge_netflow_24h is not None:
            summary += (
                f" 跨链桥 24h 净流量 {self._format_signed_money(bridge_netflow_24h)}。"
            )
        else:
            summary += f" {bridge_note}。"
        summary += f" {liquidation_note}。"

        return DefiLlamaOverview(
            stablecoin_mcap=self._format_money(stablecoin_mcap),
            stablecoin_supply_change_1d=self._format_signed_money(
                stablecoin_supply_change_1d
            ),
            stablecoin_change_7d=self._format_percent(stablecoin_change_7d),
            usdt_dominance=self._format_percent(usdt_dominance),
            total_tvl=self._format_money(current_tvl),
            change_1d=self._format_signed_money(change_1d),
            change_7d=self._format_signed_money(change_7d),
            true_flow_24h=true_flow_24h,
            dex_volume_24h=self._format_money(dex_volume_24h),
            dex_volume_change_7d=self._format_percent(dex_volume_change_7d),
            bridge_netflow_24h=self._format_optional_signed_money(bridge_netflow_24h),
            bridge_note=bridge_note,
            liquidation_24h=liquidation_24h,
            liquidation_note=liquidation_note,
            risk_signal=risk_signal,
            attribution_note=attribution_note,
            summary=summary,
        )

    def _build_top_protocols(
        self, items: list[dict[str, Any]]
    ) -> list[DefiLlamaProtocol]:
        limit = int(
            self.market_config.get("defillama", {}).get("top_protocol_limit", 10)
        )
        protocols = sorted(
            (
                item
                for item in items
                if isinstance(item, dict)
                and (item.get("tvl") or 0) > 0
                and "cex" not in str(item.get("category", "")).lower()
            ),
            key=lambda item: item.get("tvl") or 0,
            reverse=True,
        )[:limit]
        return [
            DefiLlamaProtocol(
                name=item.get("name", "-"),
                category=item.get("category", "DeFi"),
                tvl=self._format_money(float(item.get("tvl") or 0)),
                change_1d=self._format_percent(float(item.get("change_1d") or 0)),
                change_7d=self._format_percent(float(item.get("change_7d") or 0)),
                mcap_tvl=self._format_ratio(
                    float(item.get("mcap") or 0),
                    float(item.get("tvl") or 0),
                ),
                fees_24h=self._format_optional_money(
                    self._get_protocol_metric_total(item.get("slug"), "dailyFees")
                ),
                revenue_24h=self._format_optional_money(
                    self._get_protocol_metric_total(item.get("slug"), "dailyRevenue")
                ),
                signal=self._protocol_signal(
                    change_1d=float(item.get("change_1d") or 0),
                    change_7d=float(item.get("change_7d") or 0),
                ),
            )
            for item in protocols
        ]

    def _build_chain_rows(self, chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
        limit = int(self.market_config.get("defillama", {}).get("chain_limit", 6))
        selected = sorted(
            (
                item
                for item in chains
                if isinstance(item, dict) and float(item.get("tvl") or 0) > 0
            ),
            key=lambda item: float(item.get("tvl") or 0),
            reverse=True,
        )[:limit]
        rows: list[dict[str, Any]] = []
        for item in selected:
            name = item.get("name", "")
            if not name:
                continue
            history = self._request_list(
                f"{self.BASE_URL}/v2/historicalChainTvl/{quote(name, safe='')}"
            )
            current_tvl = float(item.get("tvl") or 0)
            baseline = self._baseline_from_history(history, days=7)
            change_7d = self._compute_change_from_values(
                current=current_tvl, baseline=baseline
            )
            change_amount = current_tvl - baseline
            bridge_netflow_24h = self._get_bridge_netflow_24h(name)
            rows.append(
                {
                    "name": name,
                    "tvl": current_tvl,
                    "change_7d": change_7d,
                    "change_7d_amount": change_amount,
                    "bridge_netflow_24h": bridge_netflow_24h,
                    "signal": self._chain_signal(
                        change_amount=change_amount,
                        bridge_netflow_24h=bridge_netflow_24h,
                    ),
                }
            )
        return rows

    def _build_chain_summary(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "主流链资金方向暂不可用。"
        bridge_rows = [
            item for item in rows if item.get("bridge_netflow_24h") is not None
        ]
        if bridge_rows:
            positive = [item for item in bridge_rows if item["bridge_netflow_24h"] > 0]
            if len(positive) <= 1:
                return "跨链资金以普出为主，尚未出现明确抱团。"
            if len(positive) < len(bridge_rows):
                leaders = " / ".join(item["name"] for item in positive[:2])
                return f"跨链资金出现局部抱团，净流入主要集中在 {leaders}。"
            return "跨链资金多数回流，风险偏好有扩散迹象。"
        positive = [item for item in rows if item["change_7d_amount"] > 0]
        if len(positive) <= 1:
            return "主流链 TVL 变化以普跌为主，尚未出现明确抱团。"
        if len(positive) < len(rows):
            leaders = " / ".join(item["name"] for item in positive[:2])
            return f"主流链 TVL 出现局部修复，强势链主要集中在 {leaders}。"
        return "主流链 TVL 多数修复，风险偏好有扩散迹象。"

    def _build_category_rows(
        self, protocols: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        watchlist = self.market_config.get("defillama", {}).get(
            "category_watchlist",
            ["Liquid Staking", "Lending", "Dexes"],
        )
        rows: list[dict[str, Any]] = []
        for category in watchlist:
            aliases = self._category_aliases(category)
            selected = [
                item
                for item in protocols
                if isinstance(item, dict)
                and item.get("category") in aliases
                and (item.get("tvl") or 0) > 0
                and "cex" not in str(item.get("category", "")).lower()
            ]
            current_tvl = sum(float(item.get("tvl") or 0) for item in selected)
            baseline = sum(
                self._baseline_from_change(
                    current=float(item.get("tvl") or 0),
                    pct_change=float(item.get("change_7d") or 0),
                )
                for item in selected
            )
            change_7d = self._compute_change_from_values(
                current=current_tvl, baseline=baseline
            )
            netflow_7d = current_tvl - baseline
            rows.append(
                {
                    "display_name": self._translate_category(category),
                    "tvl": current_tvl,
                    "change_7d": change_7d,
                    "netflow_7d": netflow_7d,
                    "signal": self._category_signal(change_7d),
                }
            )
        return rows

    def _build_category_summary(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "赛道资金方向暂不可用。"
        stressed = [
            item["display_name"] for item in rows if item["signal"] == "持续失血"
        ]
        if len(stressed) >= 2:
            return f"{' / '.join(stressed)} 持续失血，赛道层面偏系统性走弱。"
        if stressed:
            return f"{stressed[0]} 失血最明显，先排查是否为单赛道利空。"
        return "主看赛道暂未出现系统性失血，资金仍在局部轮动。"

    def _build_peg_risks(
        self, stablecoins_payload: dict[str, Any]
    ) -> list[DefiLlamaPegRisk]:
        watchlist = self.market_config.get("defillama", {}).get(
            "peg_watchlist",
            ["USDT", "USDC", "USDe", "DAI", "FDUSD"],
        )
        assets = {
            item.get("symbol"): item
            for item in stablecoins_payload.get("peggedAssets", [])
            if isinstance(item, dict)
            and item.get("pegType") == "peggedUSD"
            and item.get("symbol")
        }
        selected = [assets[symbol] for symbol in watchlist if symbol in assets]
        selected.sort(
            key=lambda item: abs(float(item.get("price") or 1) - 1),
            reverse=True,
        )
        return [
            DefiLlamaPegRisk(
                symbol=item.get("symbol", "-"),
                price=f"{float(item.get('price') or 0):.4f}",
                deviation=self._format_signed_percent(
                    (float(item.get("price") or 1) - 1) * 100
                ),
                market_cap=self._format_money(
                    float((item.get("circulating") or {}).get("peggedUSD") or 0)
                ),
                supply_change_1d=self._format_signed_money(
                    float((item.get("circulating") or {}).get("peggedUSD") or 0)
                    - float(
                        (item.get("circulatingPrevDay") or {}).get("peggedUSD") or 0
                    )
                ),
                status=self._peg_status(float(item.get("price") or 1)),
            )
            for item in selected
        ]

    def _build_peg_summary(self, rows: list[DefiLlamaPegRisk]) -> str:
        if not rows:
            return "稳定币脱锚监控暂不可用。"
        alerts = [item.symbol for item in rows if item.status != "正常"]
        if alerts:
            return f"需优先盯住 {' / '.join(alerts[:3])} 的脱锚风险。"
        return "主流稳定币当前未见明显脱锚风险。"

    def _build_protocol_summary(self, rows: list[DefiLlamaProtocol]) -> str:
        if not rows:
            return "头部协议对比暂不可用。"
        down_7d = [item for item in rows if item.change_7d.startswith("-")]
        if len(down_7d) >= max(6, len(rows) // 2 + 1):
            return "头部协议多数同步回落，下跌更像全市场共性。"
        weakest = min(rows, key=lambda item: self._parse_percent(item.change_7d))
        return f"下跌更偏局部事件，当前最弱的是 {weakest.name}。"

    def _get_bridge_netflow_24h(self, chain: str) -> float | None:
        watchlist = set(
            self.market_config.get("defillama", {}).get(
                "bridge_watchlist",
                ["Ethereum", "Solana", "Arbitrum", "Base"],
            )
        )
        if chain != "all" and chain not in watchlist:
            return None
        try:
            history = self._request_list(
                f"{self.BRIDGES_BASE_URL}/bridgevolume/{quote(chain, safe='')}"
            )
        except Exception:
            return None
        if not history:
            return None
        latest = history[-1]
        return float(latest.get("depositUSD") or 0) - float(
            latest.get("withdrawUSD") or 0
        )

    def _get_protocol_metric_total(
        self, slug: str | None, data_type: str
    ) -> float | None:
        if not slug:
            return None
        try:
            payload = self._request_dict(
                f"{self.BASE_URL}/summary/fees/{quote(slug, safe='')}"
                f"?dataType={quote(data_type, safe='')}"
            )
        except Exception:
            return None
        return float(payload.get("total24h") or 0)

    def _request_list(self, url: str) -> list[dict[str, Any]]:
        data = self._request_json(url)
        if not isinstance(data, list):
            raise RuntimeError(f"DefiLlama response is not a list: url={url}")
        return data

    def _request_dict(self, url: str) -> dict[str, Any]:
        data = self._request_json(url)
        if not isinstance(data, dict):
            raise RuntimeError(f"DefiLlama response is not a dict: url={url}")
        return data

    def _request_json(self, url: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            session = requests.Session()
            session.trust_env = False
            try:
                response = session.get(
                    url,
                    headers={"Accept": "application/json"},
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"DefiLlama request failed: status={response.status_code}, body={response.text[:300]}, url={url}"
                    )
                return response.json()
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt == 2:
                    break
                time.sleep(1)
        raise RuntimeError(f"DefiLlama request failed after retries: {last_error}")

    def _compute_change_amount_from_history(
        self, history: list[dict[str, Any]], days: int
    ) -> float:
        latest = float(history[-1].get("tvl") or 0)
        baseline = self._baseline_from_history(history, days=days)
        return latest - baseline

    def _baseline_from_history(self, history: list[dict[str, Any]], days: int) -> float:
        baseline_index = max(0, len(history) - 1 - days)
        return float(history[baseline_index].get("tvl") or 0)

    @staticmethod
    def _baseline_from_change(current: float, pct_change: float) -> float:
        denominator = 1 + pct_change / 100
        if current <= 0 or denominator <= 0:
            return current
        return current / denominator

    @staticmethod
    def _compute_change_from_values(current: float, baseline: float) -> float:
        if baseline == 0:
            return 0.0
        return (current - baseline) / baseline * 100

    @staticmethod
    def _translate_category(category: str) -> str:
        mapping = {
            "Liquid Staking": "质押",
            "Lending": "借贷",
            "Dexs": "DEX",
            "Dexes": "DEX",
        }
        return mapping.get(category, category)

    @staticmethod
    def _category_aliases(category: str) -> set[str]:
        mapping = {
            "Dexes": {"Dexes", "Dexs"},
            "Dexs": {"Dexes", "Dexs"},
        }
        return mapping.get(category, {category})

    @staticmethod
    def _category_signal(change_7d: float) -> str:
        if change_7d <= -5:
            return "持续失血"
        if change_7d < 0:
            return "缓慢流出"
        return "相对抗跌"

    @staticmethod
    def _chain_signal(change_amount: float, bridge_netflow_24h: float | None) -> str:
        if bridge_netflow_24h is not None:
            if bridge_netflow_24h > 0:
                return "净流入抱团"
            return "桥流量偏流出"
        if change_amount > 0:
            return "TVL 修复"
        return "TVL 承压"

    @staticmethod
    def _protocol_signal(change_1d: float, change_7d: float) -> str:
        if change_1d <= -3 or change_7d <= -10:
            return "弱势"
        if change_1d < 0 or change_7d < 0:
            return "承压"
        return "相对稳健"

    @staticmethod
    def _build_overview_risk_signal(
        stablecoin_supply_change_1d: float,
        tvl_change_1d: float,
        dex_volume_change_7d: float,
    ) -> str:
        if tvl_change_1d < 0 and dex_volume_change_7d > 0:
            return "TVL 下滑但交易放量，偏恐慌出逃"
        if tvl_change_1d < 0 and dex_volume_change_7d < 0:
            return "资金与交易同步收缩，市场偏冷"
        if stablecoin_supply_change_1d > 0 and tvl_change_1d >= 0:
            return "稳定币回流且 TVL 企稳，风险偏好修复"
        return "资金面中性偏观望，继续盯清算与桥流量"

    @staticmethod
    def _peg_status(price: float) -> str:
        deviation_pct = abs(price - 1) * 100
        if deviation_pct >= 0.5:
            return "需警惕"
        if deviation_pct >= 0.2:
            return "轻微偏离"
        return "正常"

    @staticmethod
    def _parse_percent(value: str) -> float:
        try:
            return float(value.replace("%", ""))
        except ValueError:
            return 0.0

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

    @staticmethod
    def _format_abs_money(value: float) -> str:
        return DefiLlamaClient._format_money(abs(value))

    @staticmethod
    def _format_signed_money(value: float) -> str:
        sign = "+" if value >= 0 else "-"
        return f"{sign}{DefiLlamaClient._format_abs_money(value)}"

    @staticmethod
    def _format_optional_money(value: float | None) -> str:
        if value is None:
            return "-"
        return DefiLlamaClient._format_money(value)

    @staticmethod
    def _format_optional_signed_money(value: float | None) -> str:
        if value is None:
            return "-"
        return DefiLlamaClient._format_signed_money(value)

    @staticmethod
    def _format_percent(value: float) -> str:
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.2f}%"

    @staticmethod
    def _format_signed_percent(value: float) -> str:
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.2f}%"

    @staticmethod
    def _format_ratio(numerator: float, denominator: float) -> str:
        if numerator <= 0 or denominator <= 0:
            return "-"
        return f"{numerator / denominator:.2f}x"
