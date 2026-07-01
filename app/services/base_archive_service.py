from __future__ import annotations

from datetime import datetime

from app.models.tweet import WorthReadingTweet
from app.parsers.tags_parser import parse_tags


class BaseArchiveService:
    def build_payload(self, tweets: list[WorthReadingTweet], crawled_at: datetime) -> dict:
        rows = []
        for tweet in tweets:
            parsed = parse_tags(tweet.tags)
            rows.append(
                {
                    "tweet_id": tweet.tweet_id,
                    "report_date": tweet.report_date,
                    "kol": tweet.kol_username,
                    "tweet_url": tweet.tweet_url,
                    "tweet_created_at": tweet.created_at.isoformat() if tweet.created_at else "",
                    "text": tweet.text or "",
                    "tags": ", ".join(tweet.tags),
                    "topic": ", ".join(parsed.get("Topic", [])),
                    "asset": ", ".join(parsed.get("Asset", [])),
                    "type_tag": ", ".join(parsed.get("Type", [])),
                    "likes": tweet.like_count,
                    "retweets": tweet.retweet_count,
                    "replies": tweet.reply_count,
                    "quotes": tweet.quote_count,
                    "crawl_status": tweet.crawl_status,
                    "crawled_at": crawled_at.isoformat(),
                }
            )
        return {"fields": list(rows[0].keys()) if rows else [], "rows": rows}
