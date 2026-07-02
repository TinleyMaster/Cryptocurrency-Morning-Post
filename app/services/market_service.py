from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.clients.cmc_client import CmcClient
from app.clients.coinglass_client import CoinGlassClient
from app.clients.defillama_client import DefiLlamaClient
from app.clients.dune_client import DuneClient
from app.clients.feishu_client import FeishuClient
from app.clients.helius_client import HeliusClient
from app.logger import log_event
from app.models.market import (
    DefiLlamaMonitor,
    DefiLlamaOverview,
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

    def run_daily_report(self) -> dict[str, Any]:
        now_dt = now_in_timezone(self.settings.timezone)
        snapshot = self._get_market_snapshot()
        defillama_monitor = self._get_defillama_monitor()
        helius_monitor, helius_state = self._get_helius_monitor()
        narratives = self._get_trending_narratives()
        top_coins = self._get_top_coins()
        whales = self._get_whale_observations()
        title = f"{report_date_str(now_dt)} 加密市场早报"
        context = {
            "title": title,
            "generated_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "one_liner": "市场仍处于可观察、可跟踪的阶段，但还不是适合激进加杠杆的时点。",
            "snapshot": snapshot,
            "defillama": defillama_monitor,
            "helius": helius_monitor,
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
            message_id = self.publisher.send_summary(
                title=title,
                content=self._build_summary_markdown(
                    title=title,
                    snapshot=snapshot.summary,
                    defillama_summary=defillama_monitor.overview.summary,
                    helius_summary=helius_monitor.summary,
                    doc_url=doc_url,
                    doc_note=doc_note,
                ),
            )
        log_event(
            self.logger,
            job="market_report",
            stage="publish",
            status="success",
            doc_url=doc_url,
            doc_note=doc_note,
            message_id=message_id,
        )
        return {
            "report_path": report_path,
            "doc_url": doc_url,
            "message_id": message_id,
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
                    true_flow_24h="-",
                    dex_volume_24h="-",
                    dex_volume_change_7d="-",
                    bridge_netflow_24h="-",
                    bridge_note="-",
                    liquidation_24h="-",
                    liquidation_note="-",
                    risk_signal="-",
                    attribution_note="-",
                    summary=f"DefiLlama 资金监控数据暂不可用：{exc}",
                ),
                chain_summary="主流链资金方向暂不可用。",
                chain_flows=[],
                category_summary="赛道资金方向暂不可用。",
                category_flows=[],
                peg_summary="稳定币脱锚监控暂不可用。",
                peg_risks=[],
                protocol_summary="头部协议对比暂不可用。",
                top_protocols=[],
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

    def _build_summary_markdown(
        self,
        title: str,
        snapshot: str,
        defillama_summary: str,
        helius_summary: str,
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
        ]
        if doc_url:
            lines.append(f"- 云文档：{doc_url}")
        elif doc_note:
            lines.append(f"- 云文档：{doc_note}")
        return "\n".join(lines)
