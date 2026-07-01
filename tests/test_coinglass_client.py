from app.clients.coinglass_client import CoinGlassClient


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def test_coinglass_client_sums_exchange_liquidations(monkeypatch):
    responses = {
        "Binance": {
            "code": "0",
            "data": [
                {"symbol": "BTC", "liquidation_usd_24h": 100_000_000},
                {"symbol": "ETH", "liquidation_usd_24h": 50_000_000},
            ],
        },
        "OKX": {
            "code": "0",
            "data": [
                {"symbol": "BTC", "liquidation_usd_24h": 25_000_000},
                {"symbol": "ETH", "liquidation_usd_24h": 10_000_000},
            ],
        },
    }

    def fake_get(self, url, headers=None, params=None, timeout=None):  # noqa: ANN001
        assert url == "https://open-api-v4.coinglass.com/api/futures/liquidation/coin-list"
        return FakeResponse(responses[params["exchange"]])

    monkeypatch.setattr("requests.sessions.Session.get", fake_get)

    client = CoinGlassClient(
        api_key="test-key",
        market_config={"coinglass": {"exchange_watchlist": ["Binance", "OKX"]}},
    )

    assert client.get_total_liquidations_24h() == "$185.00M"


def test_coinglass_client_requires_api_key():
    client = CoinGlassClient(api_key=None)

    try:
        client.get_total_liquidations_24h()
    except RuntimeError as exc:
        assert "COINGLASS_API_KEY" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError when API key is missing")
