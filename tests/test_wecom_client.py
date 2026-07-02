from app.clients.wecom_client import WeComClient


class FakeResponse:
    def __init__(self, payload, status_code: int = 200, text: str | None = None) -> None:  # noqa: ANN001
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else str(payload)

    def json(self):  # noqa: ANN201
        return self._payload


def test_build_webhook_markdown_content_wraps_title():
    payload = WeComClient.build_webhook_markdown_content(
        title="加密市场早报",
        markdown="- 标题：测试",
    )

    assert payload["msgtype"] == "markdown"
    assert payload["markdown"]["content"].startswith("## 加密市场早报\n\n")
    assert "- 标题：测试" in payload["markdown"]["content"]


def test_send_webhook_markdown_message_uses_default_webhook(monkeypatch):
    def fake_post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        assert url == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"
        assert json["msgtype"] == "markdown"
        return FakeResponse({"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr("requests.sessions.Session.post", fake_post)
    client = WeComClient(
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"
    )

    assert (
        client.send_webhook_markdown_message("加密市场早报", "- 标题：测试") == "ok"
    )


def test_send_webhook_markdown_message_raises_for_wecom_error(monkeypatch):
    def fake_post(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        return FakeResponse({"errcode": 93000, "errmsg": "invalid webhook url"})

    monkeypatch.setattr("requests.sessions.Session.post", fake_post)
    client = WeComClient(
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"
    )

    try:
        client.send_webhook_markdown_message("加密市场早报", "- 标题：测试")
    except RuntimeError as exc:
        assert "errcode=93000" in str(exc)
        assert "invalid webhook url" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError for WeCom webhook error")
