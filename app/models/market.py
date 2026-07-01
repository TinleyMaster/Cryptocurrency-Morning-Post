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
class DefiLlamaOverview:
    stablecoin_mcap: str
    stablecoin_supply_change_1d: str
    stablecoin_change_7d: str
    usdt_dominance: str
    total_tvl: str
    change_1d: str
    change_7d: str
    true_flow_24h: str
    dex_volume_24h: str
    dex_volume_change_7d: str
    bridge_netflow_24h: str
    bridge_note: str
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
    bridge_netflow_24h: str
    signal: str


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
    chain_summary: str
    chain_flows: list[DefiLlamaChainFlow]
    category_summary: str
    category_flows: list[DefiLlamaCategoryFlow]
    peg_summary: str
    peg_risks: list[DefiLlamaPegRisk]
    protocol_summary: str
    top_protocols: list[DefiLlamaProtocol]
