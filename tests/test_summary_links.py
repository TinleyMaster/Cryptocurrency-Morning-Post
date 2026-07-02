from app.services.kol_service import KolService
from app.services.market_service import MarketService


def test_market_summary_includes_raw_doc_url() -> None:
    summary = MarketService._build_summary_markdown(
        None,
        title="2026-07-02 加密市场早报",
        snapshot="总市值回升。",
        defillama_summary="资金面偏中性。",
        helius_summary="Solana 活跃度维持高位。",
        doc_url="https://example.com/docx/test",
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
    )

    assert "- 云文档：https://example.com/docx/kol" in summary
