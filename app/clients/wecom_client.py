from __future__ import annotations

from typing import Any

import requests


class WeComClient:
    def __init__(self, webhook_url: str | None = None, timeout: int = 30) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    def has_webhook(self) -> bool:
        return bool(self.webhook_url)

    @staticmethod
    def build_webhook_markdown_content(title: str, markdown: str) -> dict[str, Any]:
        return {
            "msgtype": "markdown",
            "markdown": {"content": f"## {title}\n\n{markdown}"},
        }

    def send_webhook_markdown_message(
        self,
        title: str,
        markdown: str,
        webhook_url: str | None = None,
    ) -> str:
        target_url = webhook_url or self.webhook_url
        if not target_url:
            raise ValueError("webhook_url is required for WeCom webhook message.")

        session = requests.Session()
        session.trust_env = False
        response = session.post(
            target_url,
            headers={"Content-Type": "application/json; charset=utf-8"},
            json=self.build_webhook_markdown_content(title=title, markdown=markdown),
            timeout=self.timeout,
        )
        payload = self._parse_response(response)
        errcode = int(payload.get("errcode", 0))
        if errcode != 0:
            raise RuntimeError(
                f"WeCom webhook request failed: errcode={errcode}, errmsg={payload.get('errmsg')}"
            )
        return str(payload.get("errmsg", "ok"))

    @staticmethod
    def _parse_response(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"WeCom webhook returned non-JSON response: status={response.status_code}, body={response.text[:300]!r}"
            ) from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"WeCom webhook request failed: status={response.status_code}, body={payload}"
            )
        return payload
