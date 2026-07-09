from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketSnapshot:
    total_market_cap: str
    btc_dominance: str
    sentiment: str
    summary: str


@dataclass
class TrendingNarrative:
    name: str
    heat_rank: int
    leader_assets: list[str]


@dataclass
class TopCoin:
    symbol: str
    sector: str
    price: str
    volume_change: str
    reason: str


@dataclass
class WhaleObservation:
    chain: str
    symbol: str
    amount_usd: str
    interpretation: str


@dataclass
class HeliusStablecoinSupply:
    symbol: str
    supply: str
    change_24h: str


@dataclass
class HeliusLstSupply:
    symbol: str
    supply: str
    change_24h: str


@dataclass
class HeliusPriorityWatch:
    name: str
    address_count: int
    priority_fee_p50: str
    priority_fee_p95: str
    signal: str


@dataclass
class HeliusSolanaMonitor:
    non_vote_transactions_12h: str
    avg_tps_1h: str
    priority_fee_p50: str
    priority_fee_p95: str
    priority_fee_note: str
    protocol_priority_summary: str
    protocol_priority_watches: list[HeliusPriorityWatch]
    stablecoin_summary: str
    stablecoin_supplies: list[HeliusStablecoinSupply]
    lst_summary: str
    lst_supplies: list[HeliusLstSupply]
    summary: str


@dataclass
class DwellirHyperliquidMarket:
    symbol: str
    price: str
    change_24h: str
    volume_24h: str
    funding_rate: str
    open_interest: str
    signal: str


@dataclass
class DwellirHyperliquidMonitor:
    watchlist: str
    total_volume_24h: str
    breadth: str
    funding_tone: str
    hottest_market: str
    markets: list[DwellirHyperliquidMarket]
    summary: str


@dataclass
class DefiLlamaOverview:
    stablecoin_mcap: str
    stablecoin_supply_change_1d: str
    stablecoin_change_7d: str
    usdt_dominance: str
    total_tvl: str
    change_1d: str
    change_7d: str
    dex_volume_24h: str
    dex_volume_change_7d: str
    liquidation_24h: str
    liquidation_note: str
    risk_signal: str
    attribution_note: str
    summary: str


@dataclass
class DefiLlamaChainFlow:
    name: str
    tvl: str
    change_7d: str
    change_amount_7d: str
    signal: str


@dataclass
class DefiLlamaStablecoinChain:
    chain: str
    stablecoin_mcap: str
    change_7d: str
    signal: str


@dataclass
class DefiLlamaDexChain:
    chain: str
    volume_24h: str
    change_7d: str
    signal: str


@dataclass
class DefiLlamaOpenInterestOverview:
    total_open_interest: str
    change_1d: str
    summary: str


@dataclass
class DefiLlamaOptionsOverview:
    total_notional_24h: str
    change_1d: str
    summary: str


@dataclass
class DefiLlamaCategoryFlow:
    name: str
    tvl: str
    change_7d: str
    netflow_7d: str
    signal: str


@dataclass
class DefiLlamaPegRisk:
    symbol: str
    price: str
    deviation: str
    market_cap: str
    supply_change_1d: str
    status: str


@dataclass
class DefiLlamaProtocol:
    name: str
    category: str
    tvl: str
    change_1d: str
    change_7d: str
    mcap_tvl: str
    fees_24h: str
    revenue_24h: str
    signal: str


@dataclass
class DefiLlamaMonitor:
    overview: DefiLlamaOverview
    stablecoin_chain_summary: str
    stablecoin_chain_flows: list[DefiLlamaStablecoinChain]
    dex_chain_summary: str
    dex_chain_flows: list[DefiLlamaDexChain]
    open_interest_summary: str
    open_interest_overview: DefiLlamaOpenInterestOverview | None
    options_summary: str
    options_overview: DefiLlamaOptionsOverview | None
    chain_summary: str
    chain_flows: list[DefiLlamaChainFlow]
    category_summary: str
    category_flows: list[DefiLlamaCategoryFlow]
    peg_summary: str
    peg_risks: list[DefiLlamaPegRisk]
    protocol_summary: str
    top_protocols: list[DefiLlamaProtocol]
    fee_protocol_summary: str
    top_fee_protocols: list[DefiLlamaProtocol]
