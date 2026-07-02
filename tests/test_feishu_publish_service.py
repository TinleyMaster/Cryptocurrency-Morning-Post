from app.services.feishu_publish_service import FeishuPublishService


class DummyFeishuClient:
    def __init__(self, has_credentials: bool = True) -> None:
        self.calls: list[tuple] = []
        self.has_credentials = has_credentials

    def has_app_credentials(self) -> bool:
        return self.has_credentials

    def send_webhook_text_message(
        self, webhook_url: str, title: str, markdown: str
    ) -> str:
        self.calls.append(("webhook", webhook_url, title, markdown))
        return "ok"

    def send_rich_text_message(self, chat_id: str, title: str, markdown: str) -> str:
        self.calls.append(("chat", chat_id, title, markdown))
        return "message_id"

    def import_markdown_as_docx(self, file_path, title: str, folder_token: str) -> str:
        self.calls.append(("doc", str(file_path), title, folder_token))
        return "https://example.com/doc"


def test_send_summary_prefers_webhook():
    client = DummyFeishuClient()
    service = FeishuPublishService(
        client,
        {
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            "chat_id": "oc_xxx",
            "folder_token": "fld_xxx",
        },
    )

    result = service.send_summary("标题", "正文")

    assert result == "ok"
    assert client.calls == [
        ("webhook", "https://open.feishu.cn/open-apis/bot/v2/hook/test", "标题", "正文")
    ]


def test_can_import_docs_still_works_when_webhook_exists():
    client = DummyFeishuClient()
    service = FeishuPublishService(
        client,
        {
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            "folder_token": "fld_xxx",
        },
    )

    assert service.can_import_docs() is True


def test_get_doc_import_blocker_when_missing_app_credentials():
    client = DummyFeishuClient(has_credentials=False)
    service = FeishuPublishService(
        client,
        {
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            "folder_token": "fld_xxx",
        },
    )

    assert service.get_doc_import_blocker() == "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET"
    assert service.can_import_docs() is False
