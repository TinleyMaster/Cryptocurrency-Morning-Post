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
