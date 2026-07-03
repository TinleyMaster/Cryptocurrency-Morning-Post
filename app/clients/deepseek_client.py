from __future__ import annotations

import json
from typing import Any

import requests


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 180,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or "https://api.deepseek.com").rstrip("/")
        self.model = model or "deepseek-chat"
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("DeepSeek API key is not configured")

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected DeepSeek response: {payload}") from exc
        return self._parse_json_content(content)

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        if not content:
            raise RuntimeError("DeepSeek returned empty content")

        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise RuntimeError(f"DeepSeek did not return valid JSON: {content}")
            return json.loads(stripped[start : end + 1])
