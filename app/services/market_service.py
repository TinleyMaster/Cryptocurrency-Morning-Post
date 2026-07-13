from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.clients.cmc_client import CmcClient
from app.clients.coinglass_client import CoinGlassClient
from app.clients.defillama_client import DefiLlamaClient
from app.clients.dwellir_client import DwellirClient
from app.clients.dune_client import DuneClient
from app.clients.feishu_client import FeishuClient
from app.clients.helius_client import HeliusClient
from app.clients.wecom_client import WeComClient
from app.logger import log_event
from app.models.market import (
    DefiLlamaMonitor,
    DefiLlamaOpenInterestOverview,
    DefiLlamaOptionsOverview,
    DefiLlamaOverview,
    DwellirHyperliquidMonitor,
    HeliusSolanaMonitor,
    MarketSnapshot,
    TopCoin,
    TrendingNarrative,
    WhaleObservation,
)
from app.renderers.market_renderer import MarketRenderer
from app.services.feishu_publish_service import FeishuPublishService
from app.utils.file_utils import write_utf8
from app.utils.time_utils import now_in_timezone, report_date_str


class MarketService:
    def __init__(self, settings, logger) -> None:
        self.settings = settings
        self.logger = logger
        self.renderer = MarketRenderer()
        self.cmc = CmcClient(
            settings.env.get("CMC_API_KEY"),
            market_config=settings.market,
        )
        self.coinglass = CoinGlassClient(
            settings.env.get("COINGLASS_API_KEY"),
            market_config=settings.market,
        )
        self.helius = HeliusClient(
            settings.env.get("HELIUS_API_KEY"),
            rpc_url=settings.env.get("QUICKNODE_SOLANA_RPC_URL"),
            market_config=settings.market,
        )
        self.dwellir = DwellirClient(
            settings.env.get("DWELLIR_API_KEY"),
            market_config=settings.market,
        )
        self.defillama = DefiLlamaClient(market_config=settings.market)
        self.dune = DuneClient(
            settings.env.get("DUNE_API_KEY"),
            market_config=settings.market,
        )
        self.publisher = FeishuPublishService(
            FeishuClient(
                settings.env.get("FEISHU_APP_ID"), settings.env.get("FEISHU_APP_SECRET")
            ),
            settings.feishu,
        )
        self.wecom = WeComClient(settings.env.get("WECOM_BOT_WEBHOOK_URL"))

    def run_daily_report(self) -> dict[str, Any]:
        now_dt = now_in_timezone(self.settings.timezone)
        snapshot = self._get_market_snapshot()
        defillama_monitor = self._get_defillama_monitor()
        helius_monitor, helius_state = self._get_helius_monitor()
        raw_dwellir_monitor = self._get_dwellir_monitor()
        dwellir_monitor = self._normalize_dwellir_monitor(raw_dwellir_monitor)
        narratives = self._get_trending_narratives()
        top_coins = self._get_top_coins()
        whales = self._get_whale_observations()
        investment_view = self._build_investment_view(
            snapshot=snapshot,
            defillama=defillama_monitor,
            helius=helius_monitor,
            dwellir=dwellir_monitor,
        )
        data_quality_notes = self._build_data_quality_notes(
            defillama=defillama_monitor,
            dwellir=raw_dwellir_monitor,
            whales=whales,
        )
        title = f"{report_date_str(now_dt)} 加密市场早报"
        context = {
            "title": title,
            "generated_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "one_liner": investment_view["one_liner"],
            "investment_view": investment_view,
            "data_quality_notes": data_quality_notes,
            "snapshot": snapshot,
            "defillama": defillama_monitor,
            "helius": helius_monitor,
            "dwellir": dwellir_monitor,
            "narratives": narratives,
            "top_coins": top_coins,
            "whale_observations": whales,
        }
        markdown = self.renderer.render_report(context)
        report_path = Path(self.settings.output_dirs["market_dir"]) / f"{title}.md"
        write_utf8(report_path, markdown)
        if helius_state is not None:
            state_path = (
                Path(self.settings.output_dirs["base_payload_dir"])
                / "helius_market_state.json"
            )
            write_utf8(
                state_path,
                json.dumps(helius_state, ensure_ascii=False, indent=2),
            )
        doc_url = ""
        doc_note = ""
        message_id = ""
        wecom_status = ""
        summary_markdown = self._build_summary_markdown(
            title=title,
            snapshot=snapshot.summary,
            defillama_summary=defillama_monitor.overview.summary,
            helius_summary=helius_monitor.summary,
            dwellir_summary=dwellir_monitor.summary,
            doc_url=doc_url,
            doc_note=doc_note,
        )
        doc_import_blocker = self.publisher.get_doc_import_blocker()
        if doc_import_blocker:
            doc_note = f"未生成（{doc_import_blocker}）"
            log_event(
                self.logger,
                job="market_report",
                stage="feishu_doc_import",
                status="skipped",
                detail=doc_import_blocker,
            )
        else:
            try:
                doc_url = self.publisher.import_markdown_as_docx(report_path, title)
            except Exception as exc:
                doc_note = f"未生成（导入失败：{exc}）"
                log_event(
                    self.logger,
                    job="market_report",
                    stage="feishu_doc_import",
                    status="warning",
                    detail=str(exc),
                )

        if self.publisher.can_send_summary():
            summary_markdown = self._build_summary_markdown(
                title=title,
                snapshot=snapshot.summary,
                defillama_summary=defillama_monitor.overview.summary,
                helius_summary=helius_monitor.summary,
                dwellir_summary=dwellir_monitor.summary,
                doc_url=doc_url,
                doc_note=doc_note,
            )
            message_id = self.publisher.send_summary(
                title=title, content=summary_markdown
            )
        else:
            summary_markdown = self._build_summary_markdown(
                title=title,
                snapshot=snapshot.summary,
                defillama_summary=defillama_monitor.overview.summary,
                helius_summary=helius_monitor.summary,
                dwellir_summary=dwellir_monitor.summary,
                doc_url=doc_url,
                doc_note=doc_note,
            )
        if self.wecom.has_webhook():
            try:
                wecom_status = self.wecom.send_webhook_markdown_message(
                    title=title,
                    markdown=summary_markdown,
                )
            except Exception as exc:
                log_event(
                    self.logger,
                    job="market_report",
                    stage="wecom_summary",
                    status="warning",
                    detail=str(exc),
                )
        log_event(
            self.logger,
            job="market_report",
            stage="publish",
            status="success",
            doc_url=doc_url,
            doc_note=doc_note,
            message_id=message_id,
            wecom_status=wecom_status,
        )
        return {
            "report_path": report_path,
            "doc_url": doc_url,
            "message_id": message_id,
            "wecom_status": wecom_status,
        }

    def _get_market_snapshot(self) -> MarketSnapshot:
        try:
            return self.cmc.get_market_snapshot()
        except Exception as exc:
            log_event(
                self.logger,
                job="market_report",
                stage="cmc_snapshot_fetch",
                status="warning",
                detail=str(exc),
            )
            return MarketSnapshot(
                total_market_cap="-",
                btc_dominance="-",
                sentiment="-",
                summary=f"CMC 大盘快照暂不可用：{exc}",
            )

    def _get_trending_narratives(self) -> list[TrendingNarrative]:
        try:
            return self.cmc.get_trending_narratives()
        except Exception as exc:
            log_event(
                self.logger,
                job="market_report",
                stage="cmc_narratives_fetch",
                status="warning",
                detail=str(exc),
            )
            return [
                TrendingNarrative(
                    name="热点赛道暂不可用",
                    heat_rank=1,
                    leader_assets=[str(exc)],
                )
            ]

    def _get_top_coins(self) -> list[TopCoin]:
        try:
            return self.cmc.get_top_coins()
        except Exception as exc:
            log_event(
                self.logger,
                job="market_report",
                stage="cmc_top_coins_fetch",
                status="warning",
                detail=str(exc),
            )
            return [
                TopCoin(
                    symbol="-",
                    sector="-",
                    price="-",
                    volume_change="-",
                    reason=f"CMC 主流币数据暂不可用：{exc}",
                )
            ]

    def _get_whale_observations(self) -> list[WhaleObservation]:
        try:
            return self.dune.get_whale_observations()
        except Exception as exc:
            log_event(
                self.logger,
                job="market_report",
                stage="dune_fetch",
                status="warning",
                detail=str(exc),
            )
            return [
                WhaleObservation(
                    chain="-",
                    symbol="-",
                    amount_usd="-",
                    interpretation=f"Dune 数据暂不可用：{exc}",
                )
            ]

    def _get_defillama_monitor(self) -> DefiLlamaMonitor:
        try:
            monitor = self.defillama.get_monitor_snapshot()
        except Exception as exc:
            log_event(
                self.logger,
                job="market_report",
                stage="defillama_fetch",
                status="warning",
                detail=str(exc),
            )
            return DefiLlamaMonitor(
                overview=DefiLlamaOverview(
                    stablecoin_mcap="-",
                    stablecoin_supply_change_1d="-",
                    stablecoin_change_7d="-",
                    usdt_dominance="-",
                    total_tvl="-",
                    change_1d="-",
                    change_7d="-",
                    dex_volume_24h="-",
                    dex_volume_change_7d="-",
                    liquidation_24h="-",
                    liquidation_note="-",
                    risk_signal="-",
                    attribution_note="-",
                    summary=f"DefiLlama 资金监控数据暂不可用：{exc}",
                ),
                stablecoin_chain_summary="稳定币链分布暂不可用。",
                stablecoin_chain_flows=[],
                dex_chain_summary="DEX 链活跃度暂不可用。",
                dex_chain_flows=[],
                open_interest_summary="链上 OI 温度暂不可用。",
                open_interest_overview=DefiLlamaOpenInterestOverview(
                    total_open_interest="-",
                    change_1d="-",
                    summary="链上 OI 温度暂不可用。",
                ),
                options_summary="期权温度暂不可用。",
                options_overview=DefiLlamaOptionsOverview(
                    total_notional_24h="-",
                    change_1d="-",
                    summary="期权温度暂不可用。",
                ),
                chain_summary="主流链资金方向暂不可用。",
                chain_flows=[],
                category_summary="赛道资金方向暂不可用。",
                category_flows=[],
                peg_summary="稳定币脱锚监控暂不可用。",
                peg_risks=[],
                protocol_summary="头部协议对比暂不可用。",
                top_protocols=[],
                fee_protocol_summary="协议手续费榜暂不可用。",
                top_fee_protocols=[],
            )
        try:
            liquidation_24h = self.coinglass.get_total_liquidations_24h()
        except Exception as exc:
            log_event(
                self.logger,
                job="market_report",
                stage="coinglass_liquidations_fetch",
                status="warning",
                detail=str(exc),
            )
            return monitor

        summary = monitor.overview.summary
        if liquidation_24h not in summary:
            summary = f"{summary} 24h 清算总额 {liquidation_24h}。"
        return replace(
            monitor,
            overview=replace(
                monitor.overview,
                liquidation_24h=liquidation_24h,
                summary=summary,
            ),
        )

    def _get_helius_monitor(self) -> tuple[HeliusSolanaMonitor, dict[str, Any] | None]:
        state_path = (
            Path(self.settings.output_dirs["base_payload_dir"])
            / "helius_market_state.json"
        )
        previous_state: dict[str, Any] | None = None
        if state_path.exists():
            try:
                previous_state = json.loads(state_path.read_text(encoding="utf-8"))
            except ValueError:
                previous_state = None
        try:
            return self.helius.get_solana_monitor(previous_state)
        except Exception as exc:
            log_event(
                self.logger,
                job="market_report",
                stage="helius_fetch",
                status="warning",
                detail=str(exc),
            )
            return (
                HeliusSolanaMonitor(
                    non_vote_transactions_12h="-",
                    avg_tps_1h="-",
                    priority_fee_p50="-",
                    priority_fee_p95="-",
                    priority_fee_note="-",
                    protocol_priority_summary="-",
                    protocol_priority_watches=[],
                    stablecoin_summary="-",
                    stablecoin_supplies=[],
                    lst_summary="-",
                    lst_supplies=[],
                    summary=f"Helius 数据暂不可用：{exc}",
                ),
                None,
            )

    def _get_dwellir_monitor(self) -> DwellirHyperliquidMonitor:
        try:
            return self.dwellir.get_hyperliquid_market_monitor()
        except Exception as exc:
            log_event(
                self.logger,
                job="market_report",
                stage="dwellir_fetch",
                status="warning",
                detail=str(exc),
            )
            return DwellirHyperliquidMonitor(
                watchlist="-",
                total_volume_24h="-",
                breadth="-",
                funding_tone="-",
                hottest_market="-",
                markets=[],
                summary=f"Dwellir Hyperliquid 数据暂不可用：{exc}",
            )

    @staticmethod
    def _normalize_dwellir_monitor(
        monitor: DwellirHyperliquidMonitor,
    ) -> DwellirHyperliquidMonitor:
        marker = (
            "Dwellir Info Endpoint rejected this request type; "
            "automatically fell back to the official Hyperliquid endpoint."
        )
        if marker not in monitor.summary:
            return monitor
        summary = monitor.summary.replace(marker, "").replace("  ", " ").strip()
        return replace(monitor, summary=summary)

    def _build_investment_view(
        self,
        snapshot: MarketSnapshot,
        defillama: DefiLlamaMonitor,
        helius: HeliusSolanaMonitor,
        dwellir: DwellirHyperliquidMonitor,
    ) -> dict[str, str]:
        stablecoin_change_7d = self._parse_percent(
            defillama.overview.stablecoin_change_7d
        )
        dex_change_7d = self._parse_percent(defillama.overview.dex_volume_change_7d)
        oi_change_1d = self._parse_percent(
            defillama.open_interest_overview.change_1d
            if defillama.open_interest_overview
            else "-"
        )
        options_change_1d = self._parse_percent(
            defillama.options_overview.change_1d if defillama.options_overview else "-"
        )
        positive_stablecoin_chains = sum(
            1
            for item in defillama.stablecoin_chain_flows
            if self._parse_percent(item.change_7d) > 0
        )
        positive_dex_chains = sum(
            1
            for item in defillama.dex_chain_flows
            if self._parse_percent(item.change_7d) > 0
        )
        positive_fee_protocols = sum(
            1
            for item in defillama.top_fee_protocols
            if self._parse_money(item.revenue_24h) > 0
        )

        if (
            stablecoin_change_7d > 0
            and positive_stablecoin_chains >= 2
            and positive_dex_chains >= 2
        ):
            narrative = "稳定币增量与链上成交出现局部扩散，但目前仍是结构性轮动，还没进入全面 risk-on。"
        elif stablecoin_change_7d > 0:
            narrative = "稳定币总量仍在小幅扩张，但增量更多表现为局部迁移，风险偏好修复并不均衡。"
        else:
            narrative = (
                "稳定币没有形成有效增量，当前更像存量资金在主流链和防守板块之间切换。"
            )

        if positive_fee_protocols >= 3:
            earnings = "手续费与收入仍集中在少数头部协议，说明现金流修复存在，但没有扩散到更广的 DeFi 板块。"
        else:
            earnings = "协议层面的盈利修复还不扎实，更多是个别头部项目承接，而不是行业普遍改善。"

        if oi_change_1d < 0 and options_change_1d < 0:
            trading = (
                "杠杆和波动交易同步降温，短线更适合观察结构，不适合追击方向和加杠杆。"
            )
        elif oi_change_1d > 0 and options_change_1d > 0 and dex_change_7d > 0:
            trading = "现货活跃、杠杆和波动交易同步回暖，短线风险偏好在修复，但仍要防止情绪过热。"
        else:
            trading = "交易层面仍偏分化，现货活跃度和衍生品温度没有形成统一共振。"

        if stablecoin_change_7d > 0 and (oi_change_1d <= 0 or options_change_1d <= 0):
            position = "仓位上维持轻仓、低杠杆，优先主流资产与高流动性链，等待资金扩散更明确再提风险。"
            one_liner = "资金没有明显离场，但修复仍偏局部；现阶段更适合轻仓跟踪主流链与头部协议。"
        elif stablecoin_change_7d > 0 and oi_change_1d > 0 and options_change_1d > 0:
            position = (
                "可以保留核心仓位并小幅试错高流动性方向，但不宜脱离主流链和主流资产。"
            )
            one_liner = (
                "资金与交易温度同步修复，可保留核心仓位，但还没到无差别进攻的时候。"
            )
        else:
            position = (
                "继续以防守型仓位管理为主，降低题材追价冲动，把流动性放在第一位。"
            )
            one_liner = (
                "增量资金不足，当前更像存量博弈阶段，仓位上应优先防守而不是抢反弹。"
            )

        if (
            snapshot.sentiment != "-"
            and "Fear" in snapshot.sentiment
            and "防守" not in position
        ):
            position = f"{position} 情绪仍偏恐慌，仓位节奏上不宜过快。"

        if (
            helius.protocol_priority_summary != "-"
            and "明显升温" in helius.protocol_priority_summary
            and "高流动性链" in position
        ):
            trading = f"{trading} Solana 局部链上拥堵已有抬头，短线热点切换会更快。"

        if (
            dwellir.breadth != "-"
            and "上涨 1/" in dwellir.breadth
            and "全面" in narrative
        ):
            narrative = "稳定币与链上成交出现局部扩散，但价格宽度仍不足，叙事还停留在结构性轮动阶段。"

        return {
            "one_liner": one_liner,
            "narrative": narrative,
            "earnings": earnings,
            "trading": trading,
            "position": position,
        }

    def _build_data_quality_notes(
        self,
        defillama: DefiLlamaMonitor,
        dwellir: DwellirHyperliquidMonitor,
        whales: list[WhaleObservation],
    ) -> list[str]:
        notes: list[str] = []
        if "COINGLASS_API_KEY" in defillama.overview.liquidation_note:
            notes.append(
                "清算总额仍缺 CoinGlass 官方密钥，杠杆压力判断只能作为弱参考。"
            )
        if "official Hyperliquid endpoint" in dwellir.summary:
            notes.append(
                "Dwellir 代理当前不支持目标 Hyperliquid 请求类型，本期已自动回退官方 endpoint。"
            )
        if whales and "Dune 数据暂不可用" in whales[0].interpretation:
            notes.append(
                "巨鲸观察当前缺少 Dune 官方密钥，链上大额异动只覆盖到降级说明。"
            )
        if defillama.overview.summary.startswith("DefiLlama 资金监控数据暂不可用"):
            notes.append("DefiLlama 资金模块存在缺口，当期资金面判断可信度下降。")
        if not notes:
            notes.append("主要市场链路可用；未见会明显影响主结论的关键数据缺口。")
        return notes

    @staticmethod
    def _parse_percent(value: str) -> float:
        if not value or value == "-":
            return 0.0
        normalized = value.replace("%", "").replace("+", "")
        try:
            return float(normalized)
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

    def _build_summary_markdown(
        self,
        title: str,
        snapshot: str,
        defillama_summary: str,
        helius_summary: str,
        dwellir_summary: str,
        doc_url: str,
        doc_note: str,
    ) -> str:
        lines = [
            "今日加密市场早报已更新：",
            "",
            f"- 标题：{title}",
            f"- 一句话：{snapshot}",
            f"- 资金监控：{defillama_summary}",
            f"- Solana 链上：{helius_summary}",
            f"- Hyperliquid：{dwellir_summary}",
        ]
        if doc_url:
            lines.append(f"- 云文档：{doc_url}")
        elif doc_note:
            lines.append(f"- 云文档：{doc_note}")
        return "\n".join(lines)
