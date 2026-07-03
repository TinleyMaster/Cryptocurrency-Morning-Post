from app.renderers.deepread_renderer import DeepreadRenderer
from app.renderers.kol_renderer import KolRenderer


def test_kol_report_template_renders_multiline_sections():
    markdown = KolRenderer().render_report(
        {
            "title": "2026-07-03 加密KOL过去24小时监控报告",
            "window_start": "2026-07-02 10:00:00",
            "window_end": "2026-07-03 10:00:00",
            "timezone": "Asia/Shanghai",
            "total_accounts": 1,
            "fetched_accounts": 1,
            "hit_count": 1,
            "post_count": 1,
            "one_liner": "测试一句话",
            "three_points": ["点 1", "点 2", "点 3"],
            "overview": ["概览 1"],
            "groups": [
                {
                    "group_name": "测试分组",
                    "group_summary": "测试主线",
                    "hits": [
                        {
                            "username": "saylor",
                            "role": "MicroStrategy董事长",
                            "core": "核心观点",
                            "judgement": "明确判断",
                            "watch_reason": "值得关注",
                            "tweet_url": "https://x.com/saylor/status/123",
                            "tags": ["#KOL/saylor", "#Topic/BTC", "#Date/2026-07-03"],
                            "post_count": 1,
                            "engagement_label": "中",
                        }
                    ],
                }
            ],
            "consensus": ["共识 1"],
            "differences": ["分歧 1"],
            "focus_accounts": [{"username": "saylor", "reason": "值得重点跟踪"}],
            "worth_reading": [
                {
                    "display_name": "@saylor",
                    "tweet_url": "https://x.com/saylor/status/123",
                    "tags": ["#KOL/saylor", "#Topic/BTC", "#Date/2026-07-03"],
                }
            ],
            "no_post_accounts": [],
            "low_signal_accounts": [],
            "fetch_error_accounts": [],
            "report_date": "2026-07-03",
        }
    )

    assert "> 样本范围：配置名单 1 个账号；本次成功抓取 1 个\n> 结果概览：" in markdown
    assert "- 值得一读：`https://x.com/saylor/status/123`\n- 对应 tags：" in markdown


def test_deepread_template_renders_analysis_sections():
    markdown = DeepreadRenderer().render_report(
        {
            "title": "2026-07-03 值得一读推文原文与逻辑拆解",
            "source_report": "2026-07-03 加密KOL过去24小时监控报告",
            "crawl_summary": "使用 `getTwitterPostsByIds` 回抓正文与互动数据，`1` 条全部拿到可用原文",
            "one_liner": "测试一句话",
            "quick_overview": ["`@saylor`：测试概括"],
            "tweets": [
                {
                    "display_name": "@saylor",
                    "tweet_url": "https://x.com/saylor/status/123",
                    "created_at_display": "2026-07-03 01:00:00",
                    "like_count": 1,
                    "retweet_count": 2,
                    "reply_count": 3,
                    "quote_count": 4,
                    "vocabulary_note": "",
                    "vocabulary": ["Bitcoin：比特币"],
                    "text": "Bitcoin adoption keeps accelerating.",
                    "translation_note": "",
                    "sentence_pairs": [{"en": "Bitcoin adoption keeps accelerating.", "cn": "比特币采用仍在加速。"}],
                    "ai_summary": ["这是测试摘要。"],
                    "logic_structure": ["先给判断", "再给依据", "最后落到跟踪变量"],
                    "extended_thoughts": ["适合继续观察机构叙事。"],
                }
            ],
        }
    )

    assert "## 今日一句话" in markdown
    assert "### 逐句对照翻译" in markdown
    assert "1. 先给判断" in markdown
