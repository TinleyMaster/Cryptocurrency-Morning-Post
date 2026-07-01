from __future__ import annotations

from datetime import datetime

from app.clients.xpoz_client import XpozClient
from app.models.tweet import WorthReadingTweet
from app.parsers.worth_reading_parser import parse_worth_reading_items
from app.renderers.deepread_renderer import DeepreadRenderer


class DeepreadService:
    def __init__(self, xpoz_client: XpozClient | None = None) -> None:
        self.renderer = DeepreadRenderer()
        self.xpoz_client = xpoz_client

    def build_tweets(self, report_markdown: str, report_date: str) -> list[WorthReadingTweet]:
        tweets = parse_worth_reading_items(report_markdown, fallback_date=report_date)
        tweets_by_id = {}
        if self.xpoz_client and tweets:
            fetched = self.xpoz_client.get_posts_by_ids([tweet.tweet_id for tweet in tweets])
            tweets_by_id = {tweet.id: tweet for tweet in fetched}
        for tweet in tweets:
            fetched = tweets_by_id.get(tweet.tweet_id)
            if fetched:
                tweet.text = fetched.text
                tweet.created_at = fetched.created_at
                tweet.like_count = fetched.like_count
                tweet.retweet_count = fetched.retweet_count
                tweet.reply_count = fetched.reply_count
                tweet.quote_count = fetched.quote_count
                tweet.crawl_status = "ok"
                tweet.notes = "已从 xpoz 真实接口回抓正文与互动数据，后续可继续补翻译与逻辑拆解。"
            else:
                tweet.text = f"{tweet.display_name} 的正文回抓失败，请检查 xpoz 返回或稍后重试。"
                tweet.created_at = datetime.fromisoformat(f"{report_date}T10:00:00")
                tweet.like_count = 0
                tweet.retweet_count = 0
                tweet.reply_count = 0
                tweet.quote_count = 0
                tweet.crawl_status = "missing"
                tweet.notes = "当前未拿到真实正文，后续可回退到补抓或人工补录。"
        return tweets

    def render(self, title: str, source_report: str, tweets: list[WorthReadingTweet]) -> str:
        context = {
            "title": title,
            "source_report": source_report,
            "tweets": [
                {
                    **tweet.__dict__,
                    "created_at_display": tweet.created_at.strftime("%Y-%m-%d %H:%M") if tweet.created_at else "",
                }
                for tweet in tweets
            ],
        }
        return self.renderer.render_report(context)
