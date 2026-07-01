from __future__ import annotations

import re

from app.models.tweet import WorthReadingTweet
from app.utils.markdown_utils import extract_section


ITEM_RE = re.compile(
    r"- `(?P<display>@[^`]+)`[：:]\s*"
    r"`(?P<url>https://x\.com/(?P<username>[^/]+)/status/(?P<tweet_id>\d+))`"
    r"\s*\n\s*`tags`:\s*(?P<tags>(?:`[^`]+`\s*)+)",
    flags=re.MULTILINE,
)


def parse_worth_reading_items(markdown_text: str, fallback_date: str) -> list[WorthReadingTweet]:
    section = extract_section(markdown_text, "值得一读的推文链接")
    if not section:
        return []

    results: list[WorthReadingTweet] = []
    for match in ITEM_RE.finditer(section):
        tags = re.findall(r"`([^`]+)`", match.group("tags"))
        report_date = fallback_date
        for tag in tags:
            if tag.startswith("#Date/"):
                report_date = tag.split("/", 1)[1]
                break
        results.append(
            WorthReadingTweet(
                display_name=match.group("display"),
                kol_username=match.group("username"),
                tweet_url=match.group("url"),
                tweet_id=match.group("tweet_id"),
                tags=tags,
                report_date=report_date,
            )
        )
    return results
