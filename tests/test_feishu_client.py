import json

from app.clients.feishu_client import FeishuClient


def test_build_post_content_uses_md_tag():
    payload = FeishuClient.build_post_content(
        title="加密市场早报",
        markdown="今日加密市场早报已更新：\n\n- 标题：加密市场早报\n- 文档： [点击查看](https://example.com)",
    )

    parsed = json.loads(payload)
    zh_cn = parsed["zh_cn"]
    assert zh_cn["title"] == "加密市场早报"
    assert zh_cn["content"][0][0]["tag"] == "md"
    assert "[点击查看](https://example.com)" in zh_cn["content"][0][0]["text"]


def test_build_webhook_text_content_uses_plain_text():
    payload = FeishuClient.build_webhook_text_content(
        title="加密市场早报",
        markdown="今日已更新\n- 标题：加密市场早报",
    )

    assert payload["msg_type"] == "text"
    assert payload["content"]["text"].startswith("加密市场早报\n\n")
    assert "今日已更新" in payload["content"]["text"]


def test_poll_import_task_waits_for_status_2_then_returns_url(monkeypatch):
    client = FeishuClient("app_id", "app_secret")
    responses = iter(
        [
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "result": {
                        "job_status": 2,
                        "job_error_msg": "",
                    }
                },
            },
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "result": {
                        "job_status": 0,
                        "job_error_msg": "success",
                        "url": "https://example.feishu.cn/docx/abc",
                    }
                },
            },
        ]
    )

    def fake_request(method, path, params=None, json_body=None):  # noqa: ANN001
        return next(responses)

    monkeypatch.setattr(client, "_request", fake_request)
    assert (
        client._poll_import_task("ticket_123", poll_interval=0, poll_timeout=5)
        == "https://example.feishu.cn/docx/abc"
    )


def test_poll_import_task_includes_result_context_on_explicit_failure(monkeypatch):
    client = FeishuClient("app_id", "app_secret")

    def fake_request(method, path, params=None, json_body=None):  # noqa: ANN001
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "result": {
                    "job_status": 3,
                    "job_error_msg": "mount point not found or no permission",
                }
            },
        }

    monkeypatch.setattr(client, "_request", fake_request)

    try:
        client._poll_import_task("ticket_123", poll_interval=0, poll_timeout=1)
    except RuntimeError as exc:
        message = str(exc)
        assert "status=3" in message
        assert "mount point not found or no permission" in message
        assert "response={'code': 0, 'msg': 'ok'" in message
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError for failed import task")
