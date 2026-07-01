from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from app.models.market import (
    HeliusLstSupply,
    HeliusPriorityWatch,
    HeliusSolanaMonitor,
    HeliusStablecoinSupply,
)


class HeliusClient:
    BASE_URL = "https://mainnet.helius-rpc.com/"

    def __init__(
        self,
        api_key: str | None = None,
        rpc_url: str | None = None,
        market_config: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.rpc_url = rpc_url
        self.market_config = market_config or {}
        self.timeout = timeout

    def get_solana_monitor(
        self, previous_state: dict[str, Any] | None = None
    ) -> tuple[HeliusSolanaMonitor, dict[str, Any]]:
        helius_config = self.market_config.get("helius", {})
        sample_limit = int(helius_config.get("performance_sample_limit", 720))
        tps_sample_count = int(helius_config.get("tps_sample_count", 60))
        priority_watchlist = helius_config.get("priority_fee_watchlist", {})
        (
            performance_samples,
            fee_samples,
            protocol_fee_map,
        ) = self._get_performance_metrics(sample_limit, priority_watchlist)

        non_vote_12h = sum(
            int(item.get("numNonVoteTransactions") or 0) for item in performance_samples
        )
        latest_tps_samples = performance_samples[:tps_sample_count]
        total_tx_1h = sum(
            int(item.get("numTransactions") or 0) for item in latest_tps_samples
        )
        total_seconds_1h = sum(
            int(item.get("samplePeriodSecs") or 0) for item in latest_tps_samples
        )
        avg_tps_1h = total_tx_1h / total_seconds_1h if total_seconds_1h else 0.0

        priority_values = sorted(
            int(item.get("prioritizationFee") or 0) for item in fee_samples
        )
        priority_fee_p50 = self._percentile(priority_values, 0.50)
        priority_fee_p95 = self._percentile(priority_values, 0.95)
        protocol_priority_watches = self._build_protocol_priority_watches(
            priority_watchlist,
            protocol_fee_map,
        )
        priority_fee_note = (
            "全网优先费来自 QuickNode 原生 Solana RPC；协议温度计基于配置的协议相关地址样本过滤，"
            "用于观察局部抢资源迹象，不等同于精确成交成本。"
        )
        protocol_priority_summary = self._build_protocol_priority_summary(
            protocol_priority_watches
        )

        stablecoin_rows, current_stablecoin_supplies = self._build_supply_rows(
            helius_config.get("stablecoin_mints", {}),
            (previous_state or {}).get("stablecoin_supplies", {}),
            HeliusStablecoinSupply,
        )
        lst_rows, current_lst_supplies = self._build_supply_rows(
            helius_config.get("lst_mints", {}),
            (previous_state or {}).get("lst_supplies", {}),
            HeliusLstSupply,
        )

        stablecoin_summary = (
            "稳定币供给变化基于上一次日报快照，首日或缺历史快照时显示待次日生成。"
        )
        lst_summary = "LSD 供给变化用于观察 Solana 生态是否出现真实降风险，首日或缺历史快照时显示待次日生成。"
        summary = (
            f"Solana 近12h 非投票交易数 {self._format_number(non_vote_12h)}，"
            f"近1h 平均 TPS {avg_tps_1h:.2f}，"
            f"优先费 P50 {self._format_micro_lamports(priority_fee_p50)}，"
            f"P95 {self._format_micro_lamports(priority_fee_p95)}。"
        )
        state = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "stablecoin_supplies": current_stablecoin_supplies,
            "lst_supplies": current_lst_supplies,
        }
        return (
            HeliusSolanaMonitor(
                non_vote_transactions_12h=self._format_number(non_vote_12h),
                avg_tps_1h=f"{avg_tps_1h:.2f}",
                priority_fee_p50=self._format_micro_lamports(priority_fee_p50),
                priority_fee_p95=self._format_micro_lamports(priority_fee_p95),
                priority_fee_note=priority_fee_note,
                protocol_priority_summary=protocol_priority_summary,
                protocol_priority_watches=protocol_priority_watches,
                stablecoin_summary=stablecoin_summary,
                stablecoin_supplies=stablecoin_rows,
                lst_summary=lst_summary,
                lst_supplies=lst_rows,
                summary=summary,
            ),
            state,
        )

    def _get_performance_metrics(
        self,
        sample_limit: int,
        priority_watchlist: dict[str, list[str]],
    ) -> tuple[list[Any], list[Any], dict[str, list[Any]]]:
        rpc_url = self._get_performance_rpc_url()
        payloads = [
            {
                "jsonrpc": "2.0",
                "id": "performance",
                "method": "getRecentPerformanceSamples",
                "params": [sample_limit],
            },
            {
                "jsonrpc": "2.0",
                "id": "fees",
                "method": "getRecentPrioritizationFees",
                "params": [],
            },
        ]
        for name, addresses in priority_watchlist.items():
            clean_addresses = [item for item in addresses if item]
            if not clean_addresses:
                continue
            payloads.append(
                {
                    "jsonrpc": "2.0",
                    "id": f"fees:{name}",
                    "method": "getRecentPrioritizationFees",
                    "params": [clean_addresses],
                }
            )
        responses = self._post_json(rpc_url, payloads)
        if not isinstance(responses, list):
            raise RuntimeError("Solana RPC batch response is not a list")
        result_map = {str(item.get("id")): item for item in responses}
        performance_response = result_map.get("performance", {})
        fees_response = result_map.get("fees", {})
        if "error" in performance_response:
            raise RuntimeError(
                f"Solana RPC getRecentPerformanceSamples failed: {performance_response.get('error')}"
            )
        if "error" in fees_response:
            raise RuntimeError(
                f"Solana RPC getRecentPrioritizationFees failed: {fees_response.get('error')}"
            )
        performance_samples = performance_response.get("result") or []
        fee_samples = fees_response.get("result") or []
        protocol_fee_map: dict[str, list[Any]] = {}
        for name in priority_watchlist:
            response = result_map.get(f"fees:{name}", {})
            if "error" in response:
                protocol_fee_map[name] = []
                continue
            protocol_fee_map[name] = response.get("result") or []
        return performance_samples, fee_samples, protocol_fee_map

    def _rpc(self, method: str, params: list[Any] | None = None) -> Any:
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY 未配置")
        data = self._post_json(
            f"{self.BASE_URL}?api-key={self.api_key}",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params or [],
            },
        )
        if "error" in data:
            raise RuntimeError(
                f"Helius request failed: method={method}, error={data.get('error')}"
            )
        return data.get("result")

    def _post_json(self, url: str, payload: Any) -> Any:
        last_error: Exception | None = None
        response = None
        for _ in range(2):
            session = requests.Session()
            session.trust_env = False
            try:
                response = session.post(
                    url,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                break
            except requests.RequestException as exc:
                last_error = exc
                response = None
        if response is None:
            raise RuntimeError(
                f"Solana RPC request failed: url={url}, error={last_error}"
            )
        data = response.json()
        if response.status_code >= 400 or "error" in data:
            raise RuntimeError(
                f"Solana RPC request failed: status={response.status_code}, url={url}, error={data.get('error')}"
            )
        return data

    def _get_performance_rpc_url(self) -> str:
        if self.rpc_url:
            return self.rpc_url
        if self.api_key:
            return f"{self.BASE_URL}?api-key={self.api_key}"
        raise RuntimeError("QUICKNODE_SOLANA_RPC_URL 或 HELIUS_API_KEY 至少配置一个")

    def _build_supply_rows(
        self,
        mint_map: dict[str, str],
        previous_supplies: dict[str, Any],
        row_type,
    ) -> tuple[list[Any], dict[str, float]]:
        rows: list[Any] = []
        current_supplies: dict[str, float] = {}
        for symbol, mint in mint_map.items():
            payload = self._rpc("getTokenSupply", [mint, {"commitment": "finalized"}])
            value = payload.get("value", {})
            current_supply = float(
                value.get("uiAmountString") or value.get("uiAmount") or 0
            )
            current_supplies[symbol] = current_supply
            previous_supply = previous_supplies.get(symbol)
            change_24h = (
                self._format_signed_number(current_supply - float(previous_supply))
                if previous_supply is not None
                else "待次日生成"
            )
            rows.append(
                row_type(
                    symbol=symbol,
                    supply=self._format_number(current_supply),
                    change_24h=change_24h,
                )
            )
        return rows, current_supplies

    def _build_protocol_priority_watches(
        self,
        watchlist: dict[str, list[str]],
        protocol_fee_map: dict[str, list[Any]],
    ) -> list[HeliusPriorityWatch]:
        rows: list[HeliusPriorityWatch] = []
        for name, addresses in watchlist.items():
            priority_values = sorted(
                int(item.get("prioritizationFee") or 0)
                for item in protocol_fee_map.get(name, [])
            )
            p50 = self._percentile(priority_values, 0.50)
            p95 = self._percentile(priority_values, 0.95)
            rows.append(
                HeliusPriorityWatch(
                    name=name,
                    address_count=len(addresses),
                    priority_fee_p50=self._format_micro_lamports(p50),
                    priority_fee_p95=self._format_micro_lamports(p95),
                    signal=self._classify_priority_signal(p95),
                )
            )
        return rows

    @staticmethod
    def _build_protocol_priority_summary(
        rows: list[HeliusPriorityWatch],
    ) -> str:
        if not rows:
            return "协议级优先费样本未配置。"
        active_rows = [
            row
            for row in rows
            if HeliusClient._parse_micro_lamports(row.priority_fee_p95) > 0
        ]
        if not active_rows:
            return "协议级优先费整体平静，暂未看到明显抢资源迹象。"
        hottest = max(
            active_rows,
            key=lambda row: HeliusClient._parse_micro_lamports(row.priority_fee_p95),
        )
        return f"{hottest.name} 样本优先费最活跃，需留意局部交易拥堵。"

    @staticmethod
    def _classify_priority_signal(priority_fee_p95: int) -> str:
        if priority_fee_p95 >= 100_000:
            return "明显升温"
        if priority_fee_p95 >= 10_000:
            return "局部升温"
        if priority_fee_p95 > 0:
            return "轻微活跃"
        return "平静"

    @staticmethod
    def _percentile(values: list[int], ratio: float) -> int:
        if not values:
            return 0
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * ratio))))
        return values[index]

    @staticmethod
    def _format_number(value: float) -> str:
        abs_value = abs(value)
        if abs_value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        if abs_value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if abs_value >= 1_000:
            return f"{value / 1_000:.2f}K"
        return f"{value:,.2f}"

    @staticmethod
    def _format_signed_number(value: float) -> str:
        sign = "+" if value >= 0 else "-"
        return f"{sign}{HeliusClient._format_number(abs(value))}"

    @staticmethod
    def _format_micro_lamports(value: int) -> str:
        return f"{value:,} micro-lamports"

    @staticmethod
    def _parse_micro_lamports(value: str) -> int:
        raw = value.replace(" micro-lamports", "").replace(",", "").strip()
        try:
            return int(raw)
        except ValueError:
            return 0
