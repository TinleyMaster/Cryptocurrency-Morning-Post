from app.clients.defillama_client import DefiLlamaClient


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_defillama_client_builds_monitor_snapshot(monkeypatch):
    responses = {
        "https://api.llama.fi/v2/historicalChainTvl": [
            {"date": 1, "tvl": 100_000_000_000},
            {"date": 2, "tvl": 110_000_000_000},
            {"date": 3, "tvl": 120_000_000_000},
            {"date": 4, "tvl": 130_000_000_000},
            {"date": 5, "tvl": 140_000_000_000},
            {"date": 6, "tvl": 150_000_000_000},
            {"date": 7, "tvl": 160_000_000_000},
            {"date": 8, "tvl": 170_000_000_000},
        ],
        "https://api.llama.fi/v2/chains": [
            {"name": "Ethereum", "tvl": 50_000_000_000},
            {"name": "Solana", "tvl": 10_000_000_000},
            {"name": "Tron", "tvl": 8_000_000_000},
            {"name": "Base", "tvl": 7_000_000_000},
        ],
        "https://api.llama.fi/v2/historicalChainTvl/Ethereum": [
            {"date": 1, "tvl": 55_000_000_000},
            {"date": 8, "tvl": 50_000_000_000},
        ],
        "https://api.llama.fi/v2/historicalChainTvl/Solana": [
            {"date": 1, "tvl": 8_000_000_000},
            {"date": 8, "tvl": 10_000_000_000},
        ],
        "https://api.llama.fi/v2/historicalChainTvl/Tron": [
            {"date": 1, "tvl": 9_000_000_000},
            {"date": 8, "tvl": 8_000_000_000},
        ],
        "https://api.llama.fi/overview/dexs?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true": {
            "total24h": 9_500_000_000,
            "change_7d": -12.5,
        },
        "https://api.llama.fi/overview/open-interest?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true": {
            "total24h": 4_200_000_000,
            "change_1d": 6.8,
        },
        "https://api.llama.fi/overview/options?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true": {
            "total24h": 1_100_000_000,
            "change_1d": 4.2,
        },
        "https://api.llama.fi/overview/dexs/ethereum?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true": {
            "total24h": 4_800_000_000,
            "change_7d": -3.0,
        },
        "https://api.llama.fi/overview/dexs/solana?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true": {
            "total24h": 2_600_000_000,
            "change_7d": 12.0,
        },
        "https://api.llama.fi/overview/dexs/tron?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true": {
            "total24h": 900_000_000,
            "change_7d": -8.0,
        },
        "https://api.llama.fi/protocols": [
            {"name": "Binance CEX", "tvl": 50_000_000_000, "category": "CEX"},
            {
                "name": "Lido",
                "slug": "lido",
                "tvl": 30_000_000_000,
                "category": "Liquid Staking",
                "change_1d": -1.1,
                "change_7d": -10.0,
                "mcap": 9_000_000_000,
            },
            {
                "name": "ether.fi",
                "slug": "ether-fi",
                "tvl": 5_000_000_000,
                "category": "Liquid Staking",
                "change_1d": -2.0,
                "change_7d": -20.0,
            },
            {
                "name": "Aave",
                "slug": "aave",
                "tvl": 20_000_000_000,
                "category": "Lending",
                "change_1d": -0.5,
                "change_7d": -5.0,
                "mcap": 2_000_000_000,
            },
            {
                "name": "Morpho",
                "slug": "morpho",
                "tvl": 10_000_000_000,
                "category": "Lending",
                "change_1d": -1.8,
                "change_7d": -15.0,
            },
            {
                "name": "Uniswap",
                "slug": "uniswap",
                "tvl": 12_000_000_000,
                "category": "Dexes",
                "change_1d": 1.2,
                "change_7d": 3.0,
                "mcap": 6_000_000_000,
            },
            {
                "name": "Curve",
                "slug": "curve",
                "tvl": 6_000_000_000,
                "category": "Dexes",
                "change_1d": -0.4,
                "change_7d": -2.0,
            },
        ],
        "https://api.llama.fi/stablecoins": {
            "peggedAssets": [
                {
                    "symbol": "USDT",
                    "pegType": "peggedUSD",
                    "price": 0.9985,
                    "circulating": {"peggedUSD": 120_000_000_000},
                    "circulatingPrevDay": {"peggedUSD": 119_000_000_000},
                    "circulatingPrevWeek": {"peggedUSD": 118_000_000_000},
                },
                {
                    "symbol": "USDC",
                    "pegType": "peggedUSD",
                    "price": 0.9998,
                    "circulating": {"peggedUSD": 50_000_000_000},
                    "circulatingPrevDay": {"peggedUSD": 51_000_000_000},
                    "circulatingPrevWeek": {"peggedUSD": 52_000_000_000},
                },
                {
                    "symbol": "USDe",
                    "pegType": "peggedUSD",
                    "price": 0.9972,
                    "circulating": {"peggedUSD": 5_000_000_000},
                    "circulatingPrevDay": {"peggedUSD": 4_800_000_000},
                    "circulatingPrevWeek": {"peggedUSD": 6_000_000_000},
                },
                {
                    "symbol": "DAI",
                    "pegType": "peggedUSD",
                    "price": 1.0004,
                    "circulating": {"peggedUSD": 4_000_000_000},
                    "circulatingPrevDay": {"peggedUSD": 4_100_000_000},
                    "circulatingPrevWeek": {"peggedUSD": 4_200_000_000},
                },
                {
                    "symbol": "FDUSD",
                    "pegType": "peggedUSD",
                    "price": 0.9920,
                    "circulating": {"peggedUSD": 2_000_000_000},
                    "circulatingPrevDay": {"peggedUSD": 2_500_000_000},
                    "circulatingPrevWeek": {"peggedUSD": 2_100_000_000},
                },
            ]
        },
        "https://api.llama.fi/stablecoinchains": [
            {"name": "Ethereum", "totalCirculating": 100_000_000_000},
            {"name": "Tron", "totalCirculating": 55_000_000_000},
            {"name": "Solana", "totalCirculating": 12_000_000_000},
            {"name": "Base", "totalCirculating": 8_000_000_000},
        ],
        "https://api.llama.fi/stablecoincharts/Ethereum": [
            {"date": 1, "totalCirculating": 95_000_000_000},
            {"date": 8, "totalCirculating": 100_000_000_000},
        ],
        "https://api.llama.fi/stablecoincharts/Tron": [
            {"date": 1, "totalCirculating": 56_000_000_000},
            {"date": 8, "totalCirculating": 55_000_000_000},
        ],
        "https://api.llama.fi/stablecoincharts/Solana": [
            {"date": 1, "totalCirculating": 10_000_000_000},
            {"date": 8, "totalCirculating": 12_000_000_000},
        ],
        "https://api.llama.fi/stablecoincharts/Base": [
            {"date": 1, "totalCirculating": 7_500_000_000},
            {"date": 8, "totalCirculating": 8_000_000_000},
        ],
        "https://api.llama.fi/summary/fees/lido?dataType=dailyFees": {
            "total24h": 3_000_000
        },
        "https://api.llama.fi/summary/fees/lido?dataType=dailyRevenue": {
            "total24h": 300_000
        },
        "https://api.llama.fi/summary/fees/aave?dataType=dailyFees": {
            "total24h": 2_900_000
        },
        "https://api.llama.fi/summary/fees/aave?dataType=dailyRevenue": {
            "total24h": 400_000
        },
        "https://api.llama.fi/summary/fees/uniswap?dataType=dailyFees": {
            "total24h": 5_000_000
        },
        "https://api.llama.fi/summary/fees/uniswap?dataType=dailyRevenue": {
            "total24h": 850_000
        },
    }

    def fake_get(self, url, headers=None, timeout=None):  # noqa: ANN001
        return FakeResponse(responses[url])

    monkeypatch.setattr("requests.sessions.Session.get", fake_get)

    client = DefiLlamaClient(
        market_config={
            "defillama": {
                "chain_limit": 3,
                "top_protocol_limit": 3,
                "category_watchlist": ["Liquid Staking", "Lending", "Dexes"],
                "peg_watchlist": ["FDUSD", "USDe", "USDT"],
            }
        }
    )
    monitor = client.get_monitor_snapshot()

    assert monitor.overview.stablecoin_mcap == "$181.00B"
    assert monitor.overview.stablecoin_supply_change_1d == "-$400.00M"
    assert monitor.overview.total_tvl == "$170.00B"
    assert monitor.overview.change_1d == "+$10.00B"
    assert monitor.overview.change_7d == "+$70.00B"
    assert monitor.overview.dex_volume_24h == "$9.50B"
    assert monitor.overview.dex_volume_change_7d == "-12.50%"
    assert monitor.overview.liquidation_24h == "待配置官方 API"
    assert "COINGLASS_API_KEY" in monitor.overview.liquidation_note
    assert monitor.overview.risk_signal == "资金面中性偏观望，继续盯清算与桥流量"
    assert "真实资金净流入/流出" in monitor.overview.attribution_note
    assert "风险判断" in monitor.overview.summary
    assert (
        monitor.stablecoin_chain_summary
        == "稳定币增量开始扩散，当前净流入主要集中在 Ethereum / Solana。"
    )
    assert monitor.stablecoin_chain_flows[0].chain == "Ethereum"
    assert monitor.stablecoin_chain_flows[0].stablecoin_mcap == "$100.00B"
    assert monitor.stablecoin_chain_flows[0].change_7d == "+5.26%"
    assert monitor.stablecoin_chain_flows[0].signal == "稳定币净流入"
    assert monitor.stablecoin_chain_flows[1].chain == "Tron"
    assert monitor.stablecoin_chain_flows[1].signal == "轻微流出"
    assert monitor.dex_chain_summary == "链上成交修复仍集中在 Solana，扩散尚不明显。"
    assert monitor.dex_chain_flows[0].chain == "Ethereum"
    assert monitor.dex_chain_flows[0].volume_24h == "$4.80B"
    assert monitor.dex_chain_flows[0].signal == "高基数回落"
    assert monitor.dex_chain_flows[1].chain == "Solana"
    assert monitor.dex_chain_flows[1].change_7d == "+12.00%"
    assert monitor.dex_chain_flows[1].signal == "活跃修复"
    assert monitor.open_interest_summary == "链上杠杆显著抬升，需警惕追涨阶段的脆弱性。"
    assert monitor.open_interest_overview is not None
    assert monitor.open_interest_overview.total_open_interest == "$4.20B"
    assert monitor.open_interest_overview.change_1d == "+6.80%"
    assert monitor.options_summary == "期权成交温和回暖，波动预期略有抬升。"
    assert monitor.options_overview is not None
    assert monitor.options_overview.total_notional_24h == "$1.10B"
    assert monitor.options_overview.change_1d == "+4.20%"
    assert monitor.chain_summary == "主流链 TVL 变化以普跌为主，尚未出现明确抱团。"
    assert monitor.chain_flows[0].name == "Ethereum"
    assert monitor.chain_flows[0].signal == "TVL 承压"
    assert monitor.chain_flows[1].signal == "TVL 修复"
    assert monitor.category_summary == "质押 / 借贷 持续失血，赛道层面偏系统性走弱。"
    assert monitor.category_flows[0].name == "质押"
    assert monitor.category_flows[0].signal == "持续失血"
    assert monitor.category_flows[2].name == "DEX"
    assert monitor.category_flows[2].tvl == "$18.00B"
    assert monitor.peg_summary == "需优先盯住 FDUSD / USDe 的脱锚风险。"
    assert monitor.peg_risks[0].symbol == "FDUSD"
    assert monitor.peg_risks[0].supply_change_1d == "-$500.00M"
    assert monitor.peg_risks[0].status == "需警惕"
    assert monitor.protocol_summary == "下跌更偏局部事件，当前最弱的是 Lido。"
    assert monitor.top_protocols[0].name == "Lido"
    assert monitor.top_protocols[0].mcap_tvl == "0.30x"
    assert monitor.top_protocols[0].fees_24h == "$3.00M"
    assert monitor.top_protocols[0].revenue_24h == "$300.00K"
    assert monitor.top_protocols[0].signal == "弱势"
    assert monitor.fee_protocol_summary == "经营现金流仍集中在 Uniswap 等少数头部协议。"
    assert monitor.top_fee_protocols[0].name == "Uniswap"
    assert monitor.top_fee_protocols[0].fees_24h == "$5.00M"
    assert monitor.top_fee_protocols[0].revenue_24h == "$850.00K"
    assert all(protocol.category != "CEX" for protocol in monitor.top_protocols)
