from app.renderers.market_renderer import MarketRenderer


def test_market_template_renders_investment_and_quality_sections():
    markdown = MarketRenderer().render_report(
        {
            "title": "2026-07-13 加密市场早报",
            "generated_at": "2026-07-13 10:00:00",
            "one_liner": "资金没有明显离场，但修复仍偏局部。",
            "investment_view": {
                "narrative": "稳定币增量仍偏结构性迁移。",
                "earnings": "现金流仍集中在头部协议。",
                "trading": "杠杆和波动交易尚未形成共振。",
                "position": "维持轻仓、低杠杆。",
            },
            "data_quality_notes": [
                "清算总额仍缺 CoinGlass 官方密钥。",
                "Hyperliquid 已自动回退官方 endpoint。",
            ],
            "snapshot": {
                "total_market_cap": "$2.18T",
                "btc_dominance": "58.29%",
                "sentiment": "Fear (30)",
                "summary": "总市值回落但主流币未出现失序。",
            },
            "defillama": {
                "overview": {
                    "stablecoin_mcap": "$311.42B",
                    "stablecoin_supply_change_1d": "+$494.54M",
                    "total_tvl": "$73.41B",
                    "change_1d": "-$63.64M",
                    "dex_volume_24h": "$5.60B",
                    "dex_volume_change_7d": "+8.02%",
                    "liquidation_24h": "待配置官方 API",
                    "liquidation_note": "24h 清算总额需配置 COINGLASS_API_KEY",
                    "risk_signal": "TVL 下滑但交易放量，偏恐慌出逃",
                    "stablecoin_change_7d": "+0.48%",
                    "usdt_dominance": "+59.13%",
                    "change_7d": "-$1.33B",
                    "attribution_note": "TVL 变化包含币价波动。",
                    "summary": "资金面暂未形成趋势性修复。",
                },
                "stablecoin_chain_summary": "稳定币增量仍偏局部迁移。",
                "stablecoin_chain_flows": [],
                "dex_chain_summary": "成交活跃度修复不均衡。",
                "dex_chain_flows": [],
                "chain_summary": "主流链 TVL 仍偏分化。",
                "chain_flows": [],
                "category_summary": "赛道层面暂未系统性转强。",
                "category_flows": [],
                "peg_summary": "主流稳定币暂未见明显失稳。",
                "peg_risks": [],
                "protocol_summary": "头部协议表现分化。",
                "top_protocols": [],
                "fee_protocol_summary": "收入仍集中在头部协议。",
                "top_fee_protocols": [],
                "open_interest_summary": "链上杠杆整体回落。",
                "open_interest_overview": {
                    "total_open_interest": "$19.06B",
                    "change_1d": "-0.85%",
                    "summary": "杠杆整体回落。",
                },
                "options_summary": "期权成交偏弱。",
                "options_overview": {
                    "total_notional_24h": "$630.63K",
                    "change_1d": "-53.69%",
                    "summary": "市场对波动的主动定价仍偏保守。",
                },
            },
            "helius": {
                "summary": "Solana 链上活跃度维持高位。",
                "non_vote_transactions_12h": "69.37M",
                "avg_tps_1h": "3366.76",
                "priority_fee_p50": "0 micro-lamports",
                "priority_fee_p95": "0 micro-lamports",
                "priority_fee_note": "优先费来自 QuickNode RPC。",
                "protocol_priority_summary": "Raydium 样本优先费最活跃。",
                "protocol_priority_watches": [],
                "stablecoin_summary": "稳定币供给等待次日对比。",
                "stablecoin_supplies": [],
                "lst_summary": "LSD 供给等待次日对比。",
                "lst_supplies": [],
            },
            "dwellir": {
                "summary": "BTC 24h 名义成交量最活跃。",
                "watchlist": "BTC / ETH / SOL",
                "total_volume_24h": "1.85B",
                "breadth": "上涨 1/3",
                "funding_tone": "资金费率整体平静",
                "hottest_market": "BTC | 价格 63,424.50 | 24h 成交 1.06B",
                "markets": [],
            },
            "narratives": [],
            "top_coins": [],
            "whale_observations": [],
        }
    )

    assert "## 四分法判断" in markdown
    assert "- 叙事判断：稳定币增量仍偏结构性迁移。" in markdown
    assert "## 数据质量说明" in markdown
    assert "- Hyperliquid 已自动回退官方 endpoint。" in markdown
