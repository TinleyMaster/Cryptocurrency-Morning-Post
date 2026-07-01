from app.clients.helius_client import HeliusClient


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def test_helius_client_builds_solana_monitor(monkeypatch):
    def fake_post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        if url == "https://quicknode.example/":
            assert isinstance(json, list)
            ids = {item["id"] for item in json}
            assert ids == {
                "performance",
                "fees",
                "fees:Jupiter",
                "fees:Raydium",
                "fees:Kamino",
            }
            return FakeResponse(
                [
                    {
                        "id": "performance",
                        "result": [
                            {
                                "numTransactions": 6_000,
                                "numNonVoteTransactions": 3_000,
                                "samplePeriodSecs": 60,
                            },
                            {
                                "numTransactions": 6_000,
                                "numNonVoteTransactions": 2_000,
                                "samplePeriodSecs": 60,
                            },
                            {
                                "numTransactions": 3_000,
                                "numNonVoteTransactions": 1_000,
                                "samplePeriodSecs": 60,
                            },
                        ],
                    },
                    {
                        "id": "fees",
                        "result": [
                            {"prioritizationFee": 1_000},
                            {"prioritizationFee": 5_000},
                            {"prioritizationFee": 9_000},
                        ],
                    },
                    {
                        "id": "fees:Jupiter",
                        "result": [
                            {"prioritizationFee": 2_000},
                            {"prioritizationFee": 15_000},
                        ],
                    },
                    {
                        "id": "fees:Raydium",
                        "result": [
                            {"prioritizationFee": 0},
                            {"prioritizationFee": 0},
                        ],
                    },
                    {
                        "id": "fees:Kamino",
                        "result": [
                            {"prioritizationFee": 200_000},
                            {"prioritizationFee": 120_000},
                        ],
                    },
                ]
            )
        assert url == "https://mainnet.helius-rpc.com/?api-key=test-key"
        method = json["method"]
        if method == "getRecentPerformanceSamples":
            return FakeResponse(
                {
                    "result": [
                        {
                            "numTransactions": 6_000,
                            "numNonVoteTransactions": 3_000,
                            "samplePeriodSecs": 60,
                        },
                        {
                            "numTransactions": 6_000,
                            "numNonVoteTransactions": 2_000,
                            "samplePeriodSecs": 60,
                        },
                        {
                            "numTransactions": 3_000,
                            "numNonVoteTransactions": 1_000,
                            "samplePeriodSecs": 60,
                        },
                    ]
                }
            )
        if method == "getRecentPrioritizationFees":
            return FakeResponse(
                {
                    "result": [
                        {"prioritizationFee": 1_000},
                        {"prioritizationFee": 5_000},
                        {"prioritizationFee": 9_000},
                    ]
                }
            )
        mint = json["params"][0]
        supplies = {
            "USDC_MINT": "1000",
            "USDT_MINT": "2000",
            "JITOSOL_MINT": "3000",
            "MSOL_MINT": "4000",
            "BSOL_MINT": "5000",
        }
        return FakeResponse(
            {
                "result": {
                    "value": {
                        "uiAmountString": supplies[mint],
                    }
                }
            }
        )

    monkeypatch.setattr("requests.sessions.Session.post", fake_post)

    client = HeliusClient(
        api_key="test-key",
        rpc_url="https://quicknode.example/",
        market_config={
            "helius": {
                "performance_sample_limit": 3,
                "tps_sample_count": 2,
                "priority_fee_watchlist": {
                    "Jupiter": ["JUP_ADDRESS"],
                    "Raydium": ["RAY_A", "RAY_B"],
                    "Kamino": ["KAMINO_A", "KAMINO_B"],
                },
                "stablecoin_mints": {
                    "USDC": "USDC_MINT",
                    "USDT": "USDT_MINT",
                },
                "lst_mints": {
                    "JitoSOL": "JITOSOL_MINT",
                    "mSOL": "MSOL_MINT",
                    "bSOL": "BSOL_MINT",
                },
            }
        },
    )

    monitor, state = client.get_solana_monitor(
        previous_state={
            "stablecoin_supplies": {"USDC": 900.0, "USDT": 2100.0},
            "lst_supplies": {"JitoSOL": 2900.0, "mSOL": 3900.0, "bSOL": 5100.0},
        }
    )

    assert monitor.non_vote_transactions_12h == "6.00K"
    assert monitor.avg_tps_1h == "100.00"
    assert monitor.priority_fee_p50 == "5,000 micro-lamports"
    assert monitor.priority_fee_p95 == "9,000 micro-lamports"
    assert "QuickNode" in monitor.priority_fee_note
    assert (
        monitor.protocol_priority_summary
        == "Kamino 样本优先费最活跃，需留意局部交易拥堵。"
    )
    assert monitor.protocol_priority_watches[0].name == "Jupiter"
    assert (
        monitor.protocol_priority_watches[0].priority_fee_p95 == "15,000 micro-lamports"
    )
    assert monitor.protocol_priority_watches[0].signal == "局部升温"
    assert monitor.protocol_priority_watches[1].priority_fee_p95 == "0 micro-lamports"
    assert monitor.protocol_priority_watches[1].signal == "平静"
    assert (
        monitor.protocol_priority_watches[2].priority_fee_p95
        == "200,000 micro-lamports"
    )
    assert monitor.protocol_priority_watches[2].signal == "明显升温"
    assert monitor.stablecoin_supplies[0].symbol == "USDC"
    assert monitor.stablecoin_supplies[0].supply == "1.00K"
    assert monitor.stablecoin_supplies[0].change_24h == "+100.00"
    assert monitor.stablecoin_supplies[1].change_24h == "-100.00"
    assert monitor.lst_supplies[0].symbol == "JitoSOL"
    assert monitor.lst_supplies[0].change_24h == "+100.00"
    assert monitor.lst_supplies[2].change_24h == "-100.00"
    assert "非投票交易数" in monitor.summary
    assert state["stablecoin_supplies"]["USDC"] == 1000.0
    assert state["lst_supplies"]["mSOL"] == 4000.0


def test_helius_client_requires_api_key_for_supply_rows(monkeypatch):
    def fake_post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        assert url == "https://quicknode.example/"
        return FakeResponse(
            [
                {"id": "performance", "result": []},
                {"id": "fees", "result": []},
            ]
        )

    monkeypatch.setattr("requests.sessions.Session.post", fake_post)
    client = HeliusClient(
        api_key=None,
        rpc_url="https://quicknode.example/",
        market_config={"helius": {"stablecoin_mints": {"USDC": "USDC_MINT"}}},
    )

    try:
        client.get_solana_monitor()
    except RuntimeError as exc:
        assert "HELIUS_API_KEY" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError when API key is missing")
