from app.clients.dwellir_client import DwellirClient


class FakeResponse:
    def __init__(
        self,
        payload=None,  # noqa: ANN001
        status_code: int = 200,
        text: str | None = None,
        raises_json: bool = False,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else ("" if payload is None else str(payload))
        self._raises_json = raises_json

    def json(self):  # noqa: ANN201
        if self._raises_json:
            raise ValueError("invalid json")
        return self._payload


def test_dwellir_client_builds_hyperliquid_monitor(monkeypatch):
    def fake_post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        assert url == "https://api-hyperliquid-mainnet-info.n.dwellir.com/info"
        assert headers["X-Api-Key"] == "test-key"
        if json["type"] == "metaAndAssetCtxs":
            return FakeResponse(
                [
                    {
                        "universe": [
                            {"name": "BTC"},
                            {"name": "ETH"},
                            {"name": "SOL"},
                        ]
                    },
                    [
                        {
                            "dayNtlVlm": "1200000000",
                            "funding": "0.00012",
                            "openInterest": "12000",
                            "prevDayPx": "100000",
                            "markPx": "102000",
                        },
                        {
                            "dayNtlVlm": "550000000",
                            "funding": "-0.00008",
                            "openInterest": "85000",
                            "prevDayPx": "3700",
                            "markPx": "3600",
                        },
                        {
                            "dayNtlVlm": "320000000",
                            "funding": "0.00002",
                            "openInterest": "1800000",
                            "prevDayPx": "150",
                            "markPx": "152",
                        },
                    ],
                ]
            )
        assert json["type"] == "allMids"
        return FakeResponse({"BTC": "102000", "ETH": "3600", "SOL": "152"})

    monkeypatch.setattr("requests.sessions.Session.post", fake_post)

    client = DwellirClient(
        api_key="test-key",
        market_config={"dwellir": {"hyperliquid": {"symbols": ["BTC", "ETH", "SOL"]}}},
    )

    monitor = client.get_hyperliquid_market_monitor()

    assert monitor.watchlist == "BTC / ETH / SOL"
    assert monitor.total_volume_24h == "2.07B"
    assert monitor.breadth == "上涨 2/3"
    assert "BTC" in monitor.funding_tone
    assert "BTC" in monitor.hottest_market
    assert "监控池总成交额 2.07B" in monitor.summary
    assert monitor.markets[0].symbol == "BTC"
    assert monitor.markets[0].price == "102,000.00"
    assert monitor.markets[0].change_24h == "+2.00%"
    assert monitor.markets[0].volume_24h == "1.20B"
    assert monitor.markets[0].funding_rate == "+0.01%"
    assert monitor.markets[0].open_interest == "1.22B"
    assert monitor.markets[0].signal == "高流动性"
    assert monitor.markets[1].change_24h == "-2.70%"
    assert monitor.markets[2].open_interest == "273.60M"


def test_dwellir_client_requires_api_key():
    client = DwellirClient(api_key=None)

    try:
        client.get_hyperliquid_market_monitor()
    except RuntimeError as exc:
        assert "DWELLIR_API_KEY" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError when Dwellir API key is missing")


def test_dwellir_client_falls_back_to_public_info_endpoint(monkeypatch):
    def fake_post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        if url == "https://api-hyperliquid-mainnet-info.n.dwellir.com/info":
            return FakeResponse(
                status_code=422,
                text="Failed to deserialize the JSON body into the target type",
                raises_json=True,
            )
        assert url == "https://api.hyperliquid.xyz/info"
        if json["type"] == "metaAndAssetCtxs":
            return FakeResponse(
                [
                    {"universe": [{"name": "BTC"}]},
                    [
                        {
                            "dayNtlVlm": "1200000000",
                            "funding": "0.00012",
                            "openInterest": "12000",
                            "prevDayPx": "100000",
                            "markPx": "102000",
                        }
                    ],
                ]
            )
        return FakeResponse({"BTC": "102000"})

    monkeypatch.setattr("requests.sessions.Session.post", fake_post)
    client = DwellirClient(
        api_key="test-key",
        market_config={"dwellir": {"hyperliquid": {"symbols": ["BTC"]}}},
    )

    monitor = client.get_hyperliquid_market_monitor()

    assert "已自动回退官方 Hyperliquid endpoint" in monitor.summary
    assert monitor.markets[0].symbol == "BTC"
