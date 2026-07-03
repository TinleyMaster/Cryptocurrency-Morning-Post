from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TweetRecord:
    id: str
    text: str
    author_username: str
    created_at: datetime
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    quote_count: int = 0


@dataclass
class WorthReadingTweet:
    display_name: str
    kol_username: str
    tweet_url: str
    tweet_id: str
    tags: list[str]
    report_date: str
    text: str | None = None
    created_at: datetime | None = None
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    quote_count: int = 0
    crawl_status: str = "pending"
    notes: str = ""
    vocabulary_note: str = ""
    translation_note: str = ""
    vocabulary: list[str] = field(default_factory=list)
    sentence_pairs: list[dict[str, str]] = field(default_factory=list)
    ai_summary: list[str] = field(default_factory=list)
    logic_structure: list[str] = field(default_factory=list)
    extended_thoughts: list[str] = field(default_factory=list)


@dataclass
class KolHit:
    group_name: str
    username: str
    role: str
    category: str
    posts: list[TweetRecord] = field(default_factory=list)
