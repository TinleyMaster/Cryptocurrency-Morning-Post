from app.services.kol_service import KolService
from app.services.market_service import MarketService


def test_market_summary_includes_raw_doc_url() -> None:
    summary = MarketService._build_summary_markdown(
        None,
        title="2026-07-02 加密市场早报",
        snapshot="总市值回升。",
        defillama_summary="资金面偏中性。",
        helius_summary="Solana 活跃度维持高位。",
        dwellir_summary="Hyperliquid 交易活跃。",
        doc_url="https://example.com/docx/test",
        doc_note="",
    )

    assert "- 云文档：https://example.com/docx/test" in summary


def test_kol_summary_includes_raw_doc_url() -> None:
    summary = KolService._build_summary_markdown(
        None,
        title="2026-07-02 加密KOL过去24小时监控报告",
        hit_count=3,
        post_count=8,
        record_count=5,
        doc_url="https://example.com/docx/kol",
        doc_note="",
    )

    assert "- 云文档：https://example.com/docx/kol" in summary


def test_market_summary_includes_doc_note_when_doc_missing() -> None:
    summary = MarketService._build_summary_markdown(
        None,
        title="2026-07-02 加密市场早报",
        snapshot="总市值回升。",
        defillama_summary="资金面偏中性。",
        helius_summary="Solana 活跃度维持高位。",
        dwellir_summary="Hyperliquid 交易活跃。",
        doc_url="",
        doc_note="未生成（缺少 FEISHU_APP_ID / FEISHU_APP_SECRET）",
    )

    assert "- 云文档：未生成（缺少 FEISHU_APP_ID / FEISHU_APP_SECRET）" in summary


def test_market_summary_includes_dwellir_summary() -> None:
    summary = MarketService._build_summary_markdown(
        None,
        title="2026-07-02 加密市场早报",
        snapshot="总市值回升。",
        defillama_summary="资金面偏中性。",
        helius_summary="Solana 活跃度维持高位。",
        dwellir_summary="BTC 24h 成交最活跃。",
        doc_url="",
        doc_note="",
    )

    assert "- Hyperliquid：BTC 24h 成交最活跃。" in summary


def test_kol_summary_includes_doc_note_when_doc_missing() -> None:
    summary = KolService._build_summary_markdown(
        None,
        title="2026-07-02 加密KOL过去24小时监控报告",
        hit_count=3,
        post_count=8,
        record_count=5,
        doc_url="",
        doc_note="未生成（导入失败：permission denied）",
    )

    assert "- 云文档：未生成（导入失败：permission denied）" in summary
