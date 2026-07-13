from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests

from app.models.market import (
    DefiLlamaCategoryFlow,
    DefiLlamaChainFlow,
    DefiLlamaDexChain,
    DefiLlamaMonitor,
    DefiLlamaOpenInterestOverview,
    DefiLlamaOptionsOverview,
    DefiLlamaOverview,
    DefiLlamaPegRisk,
    DefiLlamaProtocol,
    DefiLlamaStablecoinChain,
)


class DefiLlamaClient:
    BASE_URL = "https://api.llama.fi"
    STABLECOINS_BASE_URL = "https://stablecoins.llama.fi"
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
            f"{self.STABLECOINS_BASE_URL}/stablecoins"
        )
        stablecoin_chains = self._request_list(
            f"{self.STABLECOINS_BASE_URL}/stablecoinchains"
        )
        dexs_overview = self._request_dict(
            f"{self.BASE_URL}/overview/dexs"
            "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
        )
        open_interest_overview = self._request_dict(
            f"{self.BASE_URL}/overview/open-interest"
            "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
        )
        options_overview = self._request_dict(
            f"{self.BASE_URL}/overview/options"
            "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
        )

        overview = self._build_overview(
            total_history,
            stablecoins_payload,
            dexs_overview,
        )
        stablecoin_chain_rows = self._build_stablecoin_chain_rows(stablecoin_chains)
        dex_chain_rows = self._build_dex_chain_rows(chains)
        open_interest_snapshot = self._build_open_interest_overview(
            open_interest_overview
        )
        chain_rows = self._build_chain_rows(chains)
        category_rows = self._build_category_rows(protocols)
        peg_risks = self._build_peg_risks(stablecoins_payload)
        top_protocols = self._build_top_protocols(protocols)
        top_fee_protocols = self._build_top_fee_protocols(top_protocols)
        options_snapshot = self._build_options_overview(options_overview)

        return DefiLlamaMonitor(
            overview=overview,
            stablecoin_chain_summary=self._build_stablecoin_chain_summary(
                stablecoin_chain_rows
            ),
            stablecoin_chain_flows=[
                DefiLlamaStablecoinChain(
                    chain=item["chain"],
                    stablecoin_mcap=self._format_money(item["stablecoin_mcap"]),
                    change_7d=self._format_percent(item["change_7d"]),
                    signal=item["signal"],
                )
                for item in stablecoin_chain_rows
            ],
            dex_chain_summary=self._build_dex_chain_summary(dex_chain_rows),
            dex_chain_flows=[
                DefiLlamaDexChain(
                    chain=item["chain"],
                    volume_24h=self._format_money(item["volume_24h"]),
                    change_7d=self._format_percent(item["change_7d"]),
                    signal=item["signal"],
                )
                for item in dex_chain_rows
            ],
            open_interest_summary=open_interest_snapshot.summary,
            open_interest_overview=open_interest_snapshot,
            options_summary=options_snapshot.summary,
            options_overview=options_snapshot,
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
            fee_protocol_summary=self._build_fee_protocol_summary(top_fee_protocols),
            top_fee_protocols=top_fee_protocols,
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
        liquidation_24h = "待配置官方 API"
        liquidation_note = self.LIQUIDATION_NOTE_KEY
        risk_signal = self._build_overview_risk_signal(
            stablecoin_supply_change_1d=stablecoin_supply_change_1d,
            tvl_change_1d=change_1d,
            dex_volume_change_7d=dex_volume_change_7d,
        )
        attribution_note = "TVL 1d/7d 变化包含币价波动，当前免费口径更适合看方向和强弱，不适合直接等同为真实资金净流入/流出。"
        summary = (
            f"稳定币总市值 {self._format_money(stablecoin_mcap)}，"
            f"全网 TVL 24h 变化 {self._format_signed_money(change_1d)}，"
            f"DEX 24h 交易量 {self._format_money(dex_volume_24h)}，"
            f"风险判断：{risk_signal}。"
        )
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
            dex_volume_24h=self._format_money(dex_volume_24h),
            dex_volume_change_7d=self._format_percent(dex_volume_change_7d),
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

    def _build_stablecoin_chain_rows(
        self, chains: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        limit = int(
            self.market_config.get("defillama", {}).get("stablecoin_chain_limit", 5)
        )
        selected = sorted(
            (
                item
                for item in chains
                if isinstance(item, dict)
                and item.get("name")
                and self._extract_stablecoin_amount(
                    item.get("totalCirculatingUSD"),
                    item.get("totalCirculating"),
                )
                > 0
            ),
            key=lambda item: self._extract_stablecoin_amount(
                item.get("totalCirculatingUSD"),
                item.get("totalCirculating"),
            ),
            reverse=True,
        )[:limit]
        rows: list[dict[str, Any]] = []
        for item in selected:
            chain = item.get("name", "")
            history = self._request_list(
                f"{self.STABLECOINS_BASE_URL}/stablecoincharts/{quote(chain, safe='')}"
            )
            current = self._extract_stablecoin_amount(
                item.get("totalCirculatingUSD"),
                item.get("totalCirculating"),
            )
            baseline = self._baseline_from_stablecoin_history(history, days=7)
            change_7d = self._compute_change_from_values(
                current=current, baseline=baseline
            )
            rows.append(
                {
                    "chain": chain,
                    "stablecoin_mcap": current,
                    "change_7d": change_7d,
                    "signal": self._stablecoin_chain_signal(change_7d),
                }
            )
        return rows

    def _build_stablecoin_chain_summary(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "稳定币链分布暂不可用。"
        positive = [item for item in rows if item["change_7d"] > 0]
        if len(positive) >= 2:
            leaders = " / ".join(item["chain"] for item in positive[:2])
            return f"稳定币增量开始扩散，当前净流入主要集中在 {leaders}。"
        if positive:
            return f"稳定币增量仍集中在 {positive[0]['chain']}，扩散尚不充分。"
        return "主流链稳定币规模多数回落，新增弹药仍显不足。"

    def _build_dex_chain_rows(
        self, chains: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        limit = int(self.market_config.get("defillama", {}).get("dex_chain_limit", 3))
        selected = sorted(
            (
                item
                for item in chains
                if isinstance(item, dict)
                and item.get("name")
                and float(item.get("tvl") or 0) > 0
            ),
            key=lambda item: float(item.get("tvl") or 0),
            reverse=True,
        )[:limit]
        rows: list[dict[str, Any]] = []
        for item in selected:
            chain = item.get("name", "")
            payload = self._request_dict(
                f"{self.BASE_URL}/overview/dexs/{quote(chain.lower(), safe='')}"
                "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
            )
            volume_24h = float(payload.get("total24h") or 0)
            change_7d = float(payload.get("change_7d") or 0)
            rows.append(
                {
                    "chain": chain,
                    "volume_24h": volume_24h,
                    "change_7d": change_7d,
                    "signal": self._dex_chain_signal(volume_24h, change_7d),
                }
            )
        return rows

    def _build_dex_chain_summary(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "DEX 链活跃度暂不可用。"
        positive = [item for item in rows if item["change_7d"] > 0]
        if len(positive) >= 2:
            leaders = " / ".join(item["chain"] for item in positive[:2])
            return f"链上成交活跃度开始扩散，当前修复主要集中在 {leaders}。"
        if positive:
            return f"链上成交修复仍集中在 {positive[0]['chain']}，扩散尚不明显。"
        hottest = max(rows, key=lambda item: item["volume_24h"])
        return f"DEX 成交整体偏弱，当前仍以 {hottest['chain']} 承接主要活跃度。"

    def _build_open_interest_overview(
        self, payload: dict[str, Any]
    ) -> DefiLlamaOpenInterestOverview:
        total_open_interest = float(payload.get("total24h") or 0)
        change_1d = float(payload.get("change_1d") or 0)
        return DefiLlamaOpenInterestOverview(
            total_open_interest=self._format_money(total_open_interest),
            change_1d=self._format_percent(change_1d),
            summary=self._open_interest_summary(total_open_interest, change_1d),
        )

    def _build_options_overview(
        self, payload: dict[str, Any]
    ) -> DefiLlamaOptionsOverview:
        total_notional_24h = float(payload.get("total24h") or 0)
        change_1d = float(payload.get("change_1d") or 0)
        return DefiLlamaOptionsOverview(
            total_notional_24h=self._format_money(total_notional_24h),
            change_1d=self._format_percent(change_1d),
            summary=self._options_summary(total_notional_24h, change_1d),
        )

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
            rows.append(
                {
                    "name": name,
                    "tvl": current_tvl,
                    "change_7d": change_7d,
                    "change_7d_amount": change_amount,
                    "signal": self._chain_signal(change_amount=change_amount),
                }
            )
        return rows

    def _build_chain_summary(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "主流链资金方向暂不可用。"
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

    def _build_top_fee_protocols(
        self, rows: list[DefiLlamaProtocol]
    ) -> list[DefiLlamaProtocol]:
        limit = int(
            self.market_config.get("defillama", {}).get("top_fee_protocol_limit", 5)
        )
        ranked = sorted(
            rows,
            key=lambda item: (
                self._parse_money(item.fees_24h),
                self._parse_money(item.revenue_24h),
                self._parse_money(item.tvl),
            ),
            reverse=True,
        )
        return ranked[:limit]

    def _build_fee_protocol_summary(self, rows: list[DefiLlamaProtocol]) -> str:
        if not rows:
            return "协议手续费榜暂不可用。"
        leader = rows[0]
        if self._parse_money(leader.revenue_24h) > 0:
            return f"经营现金流仍集中在 {leader.name} 等少数头部协议。"
        return f"手续费承接主要集中在 {leader.name}，但收入兑现仍需继续观察。"

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
    def _baseline_from_stablecoin_history(
        history: list[dict[str, Any]], days: int
    ) -> float:
        baseline_index = max(0, len(history) - 1 - days)
        row = history[baseline_index]
        return DefiLlamaClient._extract_stablecoin_amount(
            row.get("totalCirculatingUSD"),
            row.get("totalCirculating"),
        )

    @staticmethod
    def _extract_stablecoin_amount(*candidates: Any) -> float:
        for candidate in candidates:
            if isinstance(candidate, (int, float)):
                return float(candidate)
            if isinstance(candidate, dict):
                value = candidate.get("peggedUSD")
                if isinstance(value, (int, float)):
                    return float(value)
        return 0.0

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
    def _stablecoin_chain_signal(change_7d: float) -> str:
        if change_7d > 5:
            return "稳定币净流入"
        if change_7d > 0:
            return "温和增量"
        if change_7d <= -5:
            return "资金撤离"
        return "轻微流出"

    @staticmethod
    def _dex_chain_signal(volume_24h: float, change_7d: float) -> str:
        if change_7d > 5:
            return "活跃修复"
        if change_7d > 0:
            return "温和回暖"
        if volume_24h >= 1_000_000_000:
            return "高基数回落"
        return "偏冷"

    @staticmethod
    def _open_interest_summary(total_open_interest: float, change_1d: float) -> str:
        if change_1d > 5:
            return "链上杠杆显著抬升，需警惕追涨阶段的脆弱性。"
        if change_1d > 0:
            return "链上杠杆温和回升，风险偏好略有修复。"
        if total_open_interest <= 0:
            return "链上 OI 暂不可用。"
        return "链上杠杆整体回落，市场更偏防守。"

    @staticmethod
    def _options_summary(total_notional_24h: float, change_1d: float) -> str:
        if change_1d > 5:
            return "期权成交明显升温，市场开始更积极地交易波动。"
        if change_1d > 0:
            return "期权成交温和回暖，波动预期略有抬升。"
        if total_notional_24h <= 0:
            return "期权温度暂不可用。"
        return "期权成交偏弱，市场对波动的主动定价仍偏保守。"

    @staticmethod
    def _chain_signal(change_amount: float) -> str:
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
    def _parse_money(value: str) -> float:
        if not value or value == "-":
            return 0.0
        normalized = value.replace("$", "").replace(",", "")
        multiplier = 1.0
        if normalized.endswith("B"):
            multiplier = 1_000_000_000
            normalized = normalized[:-1]
        elif normalized.endswith("M"):
            multiplier = 1_000_000
            normalized = normalized[:-1]
        elif normalized.endswith("K"):
            multiplier = 1_000
            normalized = normalized[:-1]
        elif normalized.endswith("x"):
            normalized = normalized[:-1]
        try:
            return float(normalized) * multiplier
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
