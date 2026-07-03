from datetime import datetime, timezone

from app.models.tweet import TweetRecord
from app.services.deepread_service import DeepreadService


class DummyXpozClient:
    def __init__(self, text: str) -> None:
        self.text = text

    def get_posts_by_ids(self, post_ids: list[str]) -> list[TweetRecord]:
        return [
            TweetRecord(
                id=post_ids[0],
                text=self.text,
                author_username="saylor",
                created_at=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
                like_count=10,
                retweet_count=2,
                reply_count=1,
                quote_count=0,
            )
        ]


def test_build_tweets_adds_chinese_notes_for_chinese_post():
    report_markdown = """
## 值得一读的推文链接

- `@saylor`：`https://x.com/saylor/status/123`
  `tags`: `#KOL/saylor` `#Topic/BTC` `#Date/2026-07-03`
"""
    service = DeepreadService(DummyXpozClient("这是一条中文推文，讨论比特币和机构配置。"))

    tweets = service.build_tweets(report_markdown, report_date="2026-07-03")

    assert tweets[0].crawl_status == "ok"
    assert "中文" in tweets[0].vocabulary_note
    assert "中文" in tweets[0].translation_note


def test_build_tweets_adds_sentence_pairs_for_english_post():
    report_markdown = """
## 值得一读的推文链接

- `@saylor`：`https://x.com/saylor/status/123`
  `tags`: `#KOL/saylor` `#Topic/BTC` `#Date/2026-07-03`
"""
    service = DeepreadService(
        DummyXpozClient("Bitcoin adoption is accelerating. Institutions keep buying.")
    )

    tweets = service.build_tweets(report_markdown, report_date="2026-07-03")

    assert tweets[0].vocabulary
    assert tweets[0].sentence_pairs
