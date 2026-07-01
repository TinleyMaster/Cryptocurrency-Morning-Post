from app.clients.cmc_client import CmcClient


class FakeResponse:
    def __init__(
        self,
        payload: dict | None = None,
        status_code: int = 200,
        text: str | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text or ""

    def json(self) -> dict:
        return self._payload


def test_cmc_client_parses_market_snapshot_and_quotes(monkeypatch):
    responses = {
        "/trial-pro-api/v1/global-metrics/quotes/latest": {
            "status": {"error_code": 0},
            "data": {
                "quote": {
                    "USD": {
                        "total_market_cap": 2_500_000_000_000,
                        "total_volume_24h": 120_000_000_000,
                    }
                },
                "btc_dominance": 58.12,
            },
        },
        "/trial-pro-api/v3/fear-and-greed/latest": {
            "status": {"error_code": 0},
            "data": {"value": 20, "value_classification": "Extreme fear"},
        },
        "/trial-pro-api/v3/cryptocurrency/quotes/latest": {
            "status": {"error_code": 0},
            "data": [
                {
                    "symbol": "BTC",
                    "cmc_rank": 1,
                    "tags": [{"name": "Store Of Value", "category": "CATEGORY"}],
                    "quote": {"USD": {"price": 62000, "volume_change_24h": 12.34}},
                }
            ],
        },
        "/trial-pro-api/v1/cryptocurrency/categories": {
            "status": {"error_code": 0},
            "data": [
                {"id": "cat-1", "name": "AI", "volume": 100, "market_cap": 200},
            ],
        },
        "/trial-pro-api/v1/cryptocurrency/category": {
            "status": {"error_code": 0},
            "data": {
                "coins": [
                    {"symbol": "FET"},
                    {"symbol": "TAO"},
                ]
            },
        },
    }
    def fake_get(self, url, headers=None, params=None, timeout=None):  # noqa: ANN001
        path = url.replace("https://pro-api.coinmarketcap.com", "")
        return FakeResponse(responses[path])

    monkeypatch.setattr("requests.sessions.Session.get", fake_get)

    client = CmcClient(api_key=None)
    snapshot = client.get_market_snapshot()
    top_coins = client.get_top_coins()
    narratives = client.get_trending_narratives()

    assert snapshot.total_market_cap == "$2.50T"
    assert snapshot.btc_dominance == "58.12%"
    assert "Extreme fear" in snapshot.sentiment
    assert top_coins[0].symbol == "BTC"
    assert top_coins[0].sector == "Store Of Value"
    assert narratives[0].leader_assets == ["FET", "TAO"]
