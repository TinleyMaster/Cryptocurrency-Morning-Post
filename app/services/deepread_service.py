from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from app.clients.deepseek_client import DeepSeekClient
from app.clients.xpoz_client import XpozClient
from app.logger import log_event
from app.models.tweet import WorthReadingTweet
from app.parsers.worth_reading_parser import parse_worth_reading_items
from app.renderers.deepread_renderer import DeepreadRenderer


class DeepreadService:
    def __init__(
        self,
        xpoz_client: XpozClient | None = None,
        deepseek_client: DeepSeekClient | None = None,
        logger=None,
    ) -> None:
        self.renderer = DeepreadRenderer()
        self.xpoz_client = xpoz_client
        self.deepseek_client = deepseek_client
        self.logger = logger

    def build_tweets(
        self, report_markdown: str, report_date: str
    ) -> list[WorthReadingTweet]:
        tweets = parse_worth_reading_items(report_markdown, fallback_date=report_date)
        tweets_by_id = {}
        if self.xpoz_client and tweets:
            fetched = self.xpoz_client.get_posts_by_ids(
                [tweet.tweet_id for tweet in tweets]
            )
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
                tweet.notes = "已从 xpoz 真实接口回抓正文与互动数据。"
            else:
                tweet.text = (
                    f"{tweet.display_name} 的正文回抓失败，请检查 xpoz 返回或稍后重试。"
                )
                tweet.created_at = datetime.fromisoformat(f"{report_date}T10:00:00")
                tweet.like_count = 0
                tweet.retweet_count = 0
                tweet.reply_count = 0
                tweet.quote_count = 0
                tweet.crawl_status = "missing"
                tweet.notes = "当前未拿到真实正文，已退回到占位说明。"
            self._apply_default_analysis(tweet)
        return tweets

    def render(
        self, title: str, source_report: str, tweets: list[WorthReadingTweet]
    ) -> str:
        self._enrich_with_ai(tweets)
        summary = self._build_summary_sections(tweets)
        context = {
            "title": title,
            "source_report": source_report,
            "crawl_summary": summary["crawl_summary"],
            "one_liner": summary["one_liner"],
            "quick_overview": summary["quick_overview"],
            "tweets": [
                {
                    **tweet.__dict__,
                    "created_at_display": (
                        tweet.created_at.strftime("%Y-%m-%d %H:%M:%S")
                        if tweet.created_at
                        else ""
                    ),
                }
                for tweet in tweets
            ],
        }
        return self.renderer.render_report(context)

    def _enrich_with_ai(self, tweets: list[WorthReadingTweet]) -> None:
        for tweet in tweets:
            if tweet.crawl_status != "ok" or not tweet.text:
                continue
            if not self.deepseek_client or not self.deepseek_client.is_configured():
                continue
            try:
                payload = self.deepseek_client.generate_json(
                    system_prompt=self._tweet_system_prompt(),
                    user_prompt=self._tweet_user_prompt(tweet),
                    temperature=0.2,
                    max_tokens=2600,
                )
            except Exception as exc:
                self._log_warning("deepread_ai", str(exc), tweet_id=tweet.tweet_id)
                continue
            self._apply_ai_analysis(tweet, payload)

    def _build_summary_sections(
        self, tweets: list[WorthReadingTweet]
    ) -> dict[str, Any]:
        total = len(tweets)
        success = sum(1 for tweet in tweets if tweet.crawl_status == "ok")
        if total and success == total:
            crawl_summary = f"使用 `getTwitterPostsByIds` 回抓正文与互动数据，`{success}` 条全部拿到可用原文"
        elif total:
            crawl_summary = f"使用 `getTwitterPostsByIds` 回抓正文与互动数据，`{success}` / `{total}` 条拿到可用原文"
        else:
            crawl_summary = "本次 worth-reading 为空，未生成深读内容"

        if self.deepseek_client and self.deepseek_client.is_configured() and success:
            try:
                payload = self.deepseek_client.generate_json(
                    system_prompt=self._summary_system_prompt(),
                    user_prompt=self._summary_user_prompt(tweets),
                    temperature=0.2,
                    max_tokens=1800,
                )
                return {
                    "crawl_summary": crawl_summary,
                    "one_liner": self._safe_text(
                        payload.get("one_liner"),
                        "这些 worth-reading 推文更像是同一组市场线索的不同切面，而不是单一方向的共识。",
                    ),
                    "quick_overview": self._safe_list(payload.get("quick_overview")),
                }
            except Exception as exc:
                self._log_warning("deepread_summary_ai", str(exc))

        return {
            "crawl_summary": crawl_summary,
            "one_liner": "这些 worth-reading 推文覆盖了交易结构、制度窗口和链上产品化三条并行主线。",
            "quick_overview": [
                f"`{tweet.display_name}`：{self._summarize_text(tweet.text)}"
                for tweet in tweets[:8]
            ],
        }

    @staticmethod
    def _tweet_system_prompt() -> str:
        return (
            "你是机构级加密研究助理。请阅读单条推文，输出中文 JSON，字段必须包含："
            "vocabulary_note, vocabulary, translation_note, sentence_pairs, ai_summary, logic_structure, extended_thoughts。"
            "要求："
            "1. vocabulary 是 3-6 条，格式为“术语：中文解释”；若原帖主要为中文，则 vocabulary_note 给出“本条原帖为中文...”且 vocabulary 置空。"
            "2. sentence_pairs 为逐句对照翻译数组，每项包含 en 和 cn；若原帖主要为中文，则 translation_note 给出“本条原帖为中文...”且 sentence_pairs 置空。"
            "3. ai_summary 2-4 条，logic_structure 3-4 条，extended_thoughts 2-3 条。"
            "4. 不要输出交易建议，不要捏造原文里不存在的细节。"
        )

    def _tweet_user_prompt(self, tweet: WorthReadingTweet) -> str:
        payload = {
            "display_name": tweet.display_name,
            "kol_username": tweet.kol_username,
            "tweet_url": tweet.tweet_url,
            "text": tweet.text,
            "created_at": tweet.created_at.isoformat() if tweet.created_at else "",
            "engagement": {
                "likes": tweet.like_count,
                "retweets": tweet.retweet_count,
                "replies": tweet.reply_count,
                "quotes": tweet.quote_count,
            },
            "tags": tweet.tags,
        }
        return "请分析以下 worth-reading 推文并输出 JSON：\n" + json.dumps(
            payload, ensure_ascii=False, indent=2
        )

    @staticmethod
    def _summary_system_prompt() -> str:
        return (
            "你是机构级加密研究助理。请基于多条值得一读推文的分析结果，输出中文 JSON。"
            "字段必须包含：one_liner, quick_overview。"
            "其中 quick_overview 是 4-8 条，每条格式建议为“`@账号`：一句概括”。"
        )

    def _summary_user_prompt(self, tweets: list[WorthReadingTweet]) -> str:
        payload = [
            {
                "display_name": tweet.display_name,
                "tags": tweet.tags,
                "text": tweet.text,
                "ai_summary": tweet.ai_summary,
            }
            for tweet in tweets
            if tweet.crawl_status == "ok"
        ]
        return "请汇总这些值得一读推文，输出整体一句话与快速总览：\n" + json.dumps(
            payload, ensure_ascii=False, indent=2
        )

    def _apply_default_analysis(self, tweet: WorthReadingTweet) -> None:
        if self._looks_chinese(tweet.text or ""):
            tweet.vocabulary_note = (
                "本条原帖为中文，原文即为可直接阅读版本，无需词汇预习"
            )
            tweet.translation_note = "本条原帖为中文，原文即为可直接阅读版本，无需另译"
            tweet.vocabulary = []
            tweet.sentence_pairs = []
        else:
            tweet.vocabulary_note = ""
            tweet.translation_note = ""
            tweet.vocabulary = self._fallback_vocabulary(tweet.text or "")
            tweet.sentence_pairs = self._fallback_sentence_pairs(tweet.text or "")

        tweet.ai_summary = [
            f"这条推文的核心信息是：{self._summarize_text(tweet.text)}",
            "当前未启用 AI 深度拆解时，这里保留为基于原帖的规则化摘要。",
        ]
        tweet.logic_structure = [
            "先抛出核心判断或观察。",
            "再用价格、产品、政策或情绪线索提供支撑。",
            "最后把观点落到后续值得跟踪的变量上。",
        ]
        tweet.extended_thoughts = [
            "适合结合发帖者过去 1-2 周的连续表达看其观点是否一致。",
            "更适合当作研究线索，而不是孤立地把单条推文当作结论。",
        ]

    def _apply_ai_analysis(
        self, tweet: WorthReadingTweet, payload: dict[str, Any]
    ) -> None:
        vocabulary = self._safe_list(payload.get("vocabulary"))
        sentence_pairs = []
        for item in payload.get("sentence_pairs", []) or []:
            if not isinstance(item, dict):
                continue
            en = self._safe_text(item.get("en"))
            cn = self._safe_text(item.get("cn"))
            if en or cn:
                sentence_pairs.append({"en": en, "cn": cn})

        tweet.vocabulary_note = self._safe_text(payload.get("vocabulary_note"))
        tweet.translation_note = self._safe_text(payload.get("translation_note"))
        tweet.vocabulary = vocabulary
        tweet.sentence_pairs = sentence_pairs
        tweet.ai_summary = (
            self._safe_list(payload.get("ai_summary")) or tweet.ai_summary
        )
        tweet.logic_structure = (
            self._safe_list(payload.get("logic_structure")) or tweet.logic_structure
        )
        tweet.extended_thoughts = (
            self._safe_list(payload.get("extended_thoughts")) or tweet.extended_thoughts
        )

    @staticmethod
    def _looks_chinese(text: str) -> bool:
        if not text:
            return False
        cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        return cjk_count / max(len(text), 1) > 0.15

    @staticmethod
    def _fallback_vocabulary(text: str) -> list[str]:
        candidates = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b|\$[A-Za-z0-9]{2,10}", text)
        unique = []
        for item in candidates:
            if item not in unique:
                unique.append(item)
            if len(unique) >= 5:
                break
        if not unique:
            return ["当前未提取到高置信关键词，建议直接结合原文阅读。"]
        return [f"{item}：原帖中的关键术语，建议结合上下文理解。" for item in unique]

    def _fallback_sentence_pairs(self, text: str) -> list[dict[str, str]]:
        sentences = self._split_sentences(text)
        return [
            {"en": sentence, "cn": "AI 未配置时暂不翻译，请直接参考原文。"}
            for sentence in sentences[:6]
        ]

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return []
        parts = re.split(r"(?<=[.!?。！？])\s+", cleaned)
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _summarize_text(text: str | None, limit: int = 80) -> str:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return "当前未拿到原文。"
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1] + "…"

    @staticmethod
    def _safe_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            text = DeepreadService._safe_text(item)
            if text:
                result.append(text)
        return result

    @staticmethod
    def _safe_text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    def _log_warning(self, stage: str, detail: str, **extra: Any) -> None:
        if self.logger is None:
            return
        log_event(
            self.logger,
            job="kol_report",
            stage=stage,
            status="warning",
            detail=detail,
            **extra,
        )
