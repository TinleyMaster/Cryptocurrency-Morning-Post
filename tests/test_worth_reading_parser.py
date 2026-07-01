from app.parsers.worth_reading_parser import parse_worth_reading_items


def test_parse_worth_reading_items():
    markdown = """## 值得一读的推文链接

- `@saylor`：`https://x.com/saylor/status/2071565169512108251`
  `tags`: `#KOL/saylor` `#Topic/BTC` `#Date/2026-06-30`
"""
    items = parse_worth_reading_items(markdown, fallback_date="2026-06-30")
    assert len(items) == 1
    assert items[0].kol_username == "saylor"
    assert items[0].tweet_id == "2071565169512108251"


def test_parse_multiple_worth_reading_items():
    markdown = """## 值得一读的推文链接

- `@saylor`：`https://x.com/saylor/status/2071565169512108251`
  `tags`: `#KOL/saylor` `#Topic/BTC` `#Date/2026-06-30`

- `@todd`：`https://x.com/todd/status/2071777447461462329`
  `tags`: `#KOL/todd` `#Topic/ETH` `#Date/2026-06-30`
"""
    items = parse_worth_reading_items(markdown, fallback_date="2026-06-30")

    assert len(items) == 2
    assert items[1].kol_username == "todd"
    assert items[1].tweet_id == "2071777447461462329"
