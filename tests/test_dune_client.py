from app.clients.dune_client import DuneClient


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def test_dune_client_maps_query_rows(monkeypatch):
    def fake_get(self, url, headers=None, params=None, timeout=None):  # noqa: ANN001
        assert url == "https://api.dune.com/api/v1/query/123/results"
        assert headers["X-Dune-Api-Key"] == "dune-key"
        assert params["limit"] == 3
        return FakeResponse(
            {
                "state": "QUERY_STATE_COMPLETED",
                "result": {
                    "rows": [
                        {
                            "chain": "ethereum",
                            "symbol": "USDT",
                            "amount_usd": 35_000_000,
                            "interpretation": "交易所净流入放大，需要继续跟踪。",
                        }
                    ]
                },
            }
        )

    monkeypatch.setattr("requests.sessions.Session.get", fake_get)

    client = DuneClient(
        api_key="dune-key",
        market_config={"dune": {"whale_query_id": 123, "whale_limit": 3}},
    )
    observations = client.get_whale_observations()

    assert len(observations) == 1
    assert observations[0].chain == "ethereum"
    assert observations[0].symbol == "USDT"
    assert observations[0].amount_usd == "$35.00M"
    assert "继续跟踪" in observations[0].interpretation


def test_dune_client_requires_key_and_query_id():
    client_without_key = DuneClient(
        api_key=None,
        market_config={"dune": {"whale_query_id": 123}},
    )
    client_without_query = DuneClient(
        api_key="dune-key",
        market_config={"dune": {}},
    )

    try:
        client_without_key.get_whale_observations()
        raise AssertionError("expected missing key error")
    except RuntimeError as exc:
        assert "DUNE_API_KEY" in str(exc)

    try:
        client_without_query.get_whale_observations()
        raise AssertionError("expected missing query id error")
    except RuntimeError as exc:
        assert "whale_query_id" in str(exc)
