from __future__ import annotations

from pathlib import Path

from app.clients.feishu_client import FeishuClient


class FeishuPublishService:
    def __init__(self, client: FeishuClient, feishu_config: dict) -> None:
        self.client = client
        self.feishu_config = feishu_config

    def has_webhook(self) -> bool:
        return bool(self.feishu_config.get("webhook_url"))

    def can_import_docs(self) -> bool:
        return self.client.has_app_credentials() and bool(
            self.feishu_config.get("folder_token")
        )

    def can_send_summary(self) -> bool:
        return self.has_webhook() or (
            self.client.has_app_credentials()
            and bool(self.feishu_config.get("chat_id"))
        )

    def can_write_base_records(self) -> bool:
        return self.client.has_app_credentials() and bool(
            self.feishu_config.get("base_token") and self.feishu_config.get("table_id")
        )

    def import_markdown_as_docx(self, file_path: str | Path, title: str) -> str:
        folder_token = self.feishu_config.get("folder_token", "")
        return self.client.import_markdown_as_docx(
            file_path=file_path,
            title=title,
            folder_token=folder_token,
        )

    def send_summary(self, title: str, content: str) -> str:
        webhook_url = self.feishu_config.get("webhook_url", "")
        if webhook_url:
            return self.client.send_webhook_text_message(
                webhook_url,
                title=title,
                markdown=content,
            )
        chat_id = self.feishu_config.get("chat_id", "")
        return self.client.send_rich_text_message(
            chat_id, title=title, markdown=content
        )

    def batch_create_base_records(self, payload: dict) -> list[str]:
        return self.client.batch_create_base_records(
            self.feishu_config.get("base_token", ""),
            self.feishu_config.get("table_id", ""),
            payload,
        )
