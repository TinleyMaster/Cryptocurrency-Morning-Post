from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests
from dateutil.parser import isoparse
from xpoz import XpozClient as XpozSdkClient

from app.models.tweet import TweetRecord


class XpozClient:
    TRIAL_TOKEN_URL = "https://api.xpoz.ai/api/trial/token"

    def __init__(self, api_key: str | None = None, timeout: int = 300) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self._resolved_api_key: str | None = None
        self._sdk_client: XpozSdkClient | None = None

    def get_recent_posts_by_author(
        self, username: str, limit: int = 5
    ) -> list[TweetRecord]:
        client = self._get_sdk_client()
        result = client.twitter.get_posts_by_author(
            username,
            fields=[
                "id",
                "text",
                "author_username",
                "created_at_date",
                "like_count",
                "retweet_count",
                "reply_count",
                "quote_count",
            ],
            limit=limit,
        )
        return [self._to_tweet_record(item) for item in result.data]

    def get_posts_by_ids(self, post_ids: list[str]) -> list[TweetRecord]:
        if not post_ids:
            return []
        client = self._get_sdk_client()
        items = client.twitter.get_posts_by_ids(
            post_ids,
            fields=[
                "id",
                "text",
                "author_username",
                "created_at_date",
                "like_count",
                "retweet_count",
                "reply_count",
                "quote_count",
            ],
        )
        return [self._to_tweet_record(item) for item in items]

    def close(self) -> None:
        if self._sdk_client is not None:
            self._sdk_client.close()
            self._sdk_client = None

    def _get_sdk_client(self) -> XpozSdkClient:
        if self._sdk_client is None:
            self._sdk_client = XpozSdkClient(
                self._get_api_key(),
                timeout=self.timeout,
                check_update=False,
            )
        return self._sdk_client

    def _get_api_key(self) -> str:
        if self._resolved_api_key:
            return self._resolved_api_key
        if self.api_key:
            self._resolved_api_key = self.api_key
            return self._resolved_api_key

        response = requests.post(self.TRIAL_TOKEN_URL, timeout=30)
        payload = response.json()
        if response.status_code >= 400 or not payload.get("success"):
            raise RuntimeError(f"Failed to obtain xpoz trial token: {payload}")
        self._resolved_api_key = payload["data"]["accessKey"]
        return self._resolved_api_key

    @staticmethod
    def _to_tweet_record(item: Any) -> TweetRecord:
        created_at = XpozClient._parse_datetime(
            getattr(item, "created_at", None) or getattr(item, "created_at_date", None)
        )
        return TweetRecord(
            id=str(getattr(item, "id", "")),
            text=getattr(item, "text", "") or "",
            author_username=getattr(item, "author_username", "") or "",
            created_at=created_at,
            like_count=int(getattr(item, "like_count", 0) or 0),
            retweet_count=int(getattr(item, "retweet_count", 0) or 0),
            reply_count=int(getattr(item, "reply_count", 0) or 0),
            quote_count=int(getattr(item, "quote_count", 0) or 0),
        )

    @staticmethod
    def _parse_datetime(value: str | datetime | None) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif not value:
            parsed = datetime(1970, 1, 1, tzinfo=timezone.utc)
        else:
            parsed = isoparse(value)

        # XPOZ occasionally returns date-only or timezone-free values.
        if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
