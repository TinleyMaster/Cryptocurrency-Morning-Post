from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.kol import KolProfile
from app.models.tweet import KolHit, TweetRecord
from app.services.kol_service import KolService


class DummyPublisher:
    def __init__(
        self, blocker: str | None = None, exc: Exception | None = None
    ) -> None:
        self.blocker = blocker
        self.exc = exc

    def get_base_archive_blocker(self) -> str | None:
        return self.blocker

    def batch_create_base_records(self, payload: dict) -> list[str]:
        if self.exc is not None:
            raise self.exc
        return ["rec_1", "rec_2"]


def test_archive_base_records_returns_blocker_note(monkeypatch):
    service = KolService.__new__(KolService)
    service.publisher = DummyPublisher(
        blocker="缺少 FEISHU_BASE_TOKEN / FEISHU_TABLE_ID"
    )
    service.logger = object()
    events: list[dict] = []

    monkeypatch.setattr(
        "app.services.kol_service.log_event",
        lambda logger, **kwargs: events.append(kwargs),
    )

    record_ids, note = service._archive_base_records({"rows": [{"tweet_id": "1"}]})

    assert record_ids == []
    assert note == "未执行（缺少 FEISHU_BASE_TOKEN / FEISHU_TABLE_ID）"
    assert events[0]["stage"] == "feishu_base_archive"
    assert events[0]["status"] == "skipped"


def test_archive_base_records_downgrades_exception(monkeypatch):
    service = KolService.__new__(KolService)
    service.publisher = DummyPublisher(
        exc=RuntimeError(
            "Feishu API request failed: status=400, code=91402, msg=NOTEXIST"
        )
    )
    service.logger = object()
    events: list[dict] = []

    monkeypatch.setattr(
        "app.services.kol_service.log_event",
        lambda logger, **kwargs: events.append(kwargs),
    )

    record_ids, note = service._archive_base_records({"rows": [{"tweet_id": "1"}]})

    assert record_ids == []
    assert note.startswith("失败（Feishu API request failed")
    assert events[0]["stage"] == "feishu_base_archive"
    assert events[0]["status"] == "warning"


class DummyDeepSeek:
    def is_configured(self) -> bool:
        return False


def test_build_report_context_falls_back_without_ai():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    profiles = [
        KolProfile(
            username="saylor",
            role="MicroStrategy董事长",
            category="机构 / BTC叙事",
            group_name="海外权威创始&机构大佬",
        )
    ]
    hit = KolHit(
        group_name="海外权威创始&机构大佬",
        username="saylor",
        role="MicroStrategy董事长",
        category="机构 / BTC叙事",
        posts=[
            TweetRecord(
                id="123",
                text="Bitcoin treasury adoption keeps accelerating across institutions.",
                author_username="saylor",
                created_at=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
                like_count=100,
                retweet_count=10,
                reply_count=5,
                quote_count=1,
            )
        ],
    )

    context = service._build_report_context(
        title="2026-07-03 加密KOL过去24小时监控报告",
        start_dt=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
        end_dt=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        now_dt=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        profiles=profiles,
        hits=[hit],
        fetched_accounts=["saylor"],
        no_post_accounts=[],
        fetch_error_accounts=[],
    )

    assert context["groups"]
    assert context["worth_reading"]
    assert context["worth_reading"][0]["tags"][0] == "#KOL/saylor"
    assert context["focus_accounts"][0]["username"] == "saylor"


def test_build_report_context_rewrites_generic_one_liner():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    profiles = [
        KolProfile(
            username="CredibleCrypto",
            role="周期技术分析师",
            category="技术分析 / 周期",
            group_name="交易盘面/技术分析",
        ),
        KolProfile(
            username="EricBalchunas",
            role="ETF分析师",
            category="ETF / 机构流向",
            group_name="合规/美国监管/ETF赛道",
        ),
        KolProfile(
            username="MonetSupply",
            role="稳定币研究员",
            category="稳定币 / 收益",
            group_name="宏观 / ETF / DeFi 增量线索",
        ),
    ]
    hits = [
        KolHit(
            group_name="交易盘面/技术分析",
            username="CredibleCrypto",
            role="周期技术分析师",
            category="技术分析 / 周期",
            posts=[
                TweetRecord(
                    id="eth_thesis",
                    text="ETH is not dead and an ETH season can still return from this setup.",
                    author_username="CredibleCrypto",
                    created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
                    like_count=300,
                    retweet_count=20,
                    reply_count=10,
                    quote_count=2,
                )
            ],
        ),
        KolHit(
            group_name="合规/美国监管/ETF赛道",
            username="EricBalchunas",
            role="ETF分析师",
            category="ETF / 机构流向",
            posts=[
                TweetRecord(
                    id="etf_signal",
                    text="SEC is signaling a more pro-innovation stance toward new ETF structures.",
                    author_username="EricBalchunas",
                    created_at=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
                    like_count=200,
                    retweet_count=20,
                    reply_count=10,
                    quote_count=2,
                )
            ],
        ),
        KolHit(
            group_name="宏观 / ETF / DeFi 增量线索",
            username="MonetSupply",
            role="稳定币研究员",
            category="稳定币 / 收益",
            posts=[
                TweetRecord(
                    id="yield_signal",
                    text="Stablecoin yield products compete on execution, atomic liquidity, and user experience rather than APY alone.",
                    author_username="MonetSupply",
                    created_at=datetime(2026, 7, 3, 1, 30, tzinfo=timezone.utc),
                    like_count=180,
                    retweet_count=12,
                    reply_count=6,
                    quote_count=1,
                )
            ],
        ),
    ]

    context = service._build_report_context(
        title="2026-07-03 加密KOL过去24小时监控报告",
        start_dt=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
        end_dt=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        now_dt=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        profiles=profiles,
        hits=hits,
        fetched_accounts=[item.username for item in profiles],
        no_post_accounts=[],
        fetch_error_accounts=[],
    )

    assert "结构性叙事并行发酵" not in context["one_liner"]
    assert "ETF" in context["one_liner"] or "监管" in context["one_liner"]
    assert "稳定币" in context["one_liner"] or "收益" in context["one_liner"]


def test_build_worth_reading_prefers_informative_posts_without_external_limit():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="海外交易与数据分析KOL",
        username="Pentosh1",
        role="老牌交易博主",
        category="交易 / 结构",
        posts=[
            TweetRecord(
                id="low",
                text="gm",
                author_username="Pentosh1",
                created_at=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
            ),
            TweetRecord(
                id="high",
                text="Market structure on HYPE remains constructive, no breakdown yet and adoption plus revenues still support the thesis.",
                author_username="Pentosh1",
                created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
                like_count=500,
                retweet_count=60,
                reply_count=30,
                quote_count=10,
            ),
        ],
    )

    worth_reading = service._build_worth_reading(
        ai_payload=None,
        hit_lookup={"Pentosh1": hit},
        now_dt=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
    )

    assert len(worth_reading) == 1
    assert worth_reading[0]["tweet_url"].endswith("/high")


def test_build_worth_reading_skips_reply_style_posts_and_falls_back_to_real_thesis():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="合规/美国监管/ETF赛道",
        username="EricBalchunas",
        role="ETF分析师",
        category="ETF / 机构流向",
        posts=[
            TweetRecord(
                id="reply_like",
                text="@chromage2 That's fair. Embiid is so shaky",
                author_username="EricBalchunas",
                created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
                like_count=900,
                retweet_count=10,
                reply_count=20,
                quote_count=1,
            ),
            TweetRecord(
                id="real_signal",
                text="SEC is signaling a more pro-innovation stance toward new ETF structures while trying to avoid copycat filings cutting the line.",
                author_username="EricBalchunas",
                created_at=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
                like_count=300,
                retweet_count=40,
                reply_count=15,
                quote_count=5,
            ),
        ],
    )

    worth_reading = service._build_worth_reading(
        ai_payload={
            "worth_reading": [
                {
                    "username": "EricBalchunas",
                    "tweet_id": "reply_like",
                    "tags": ["#KOL/EricBalchunas", "#Topic/ETF"],
                }
            ]
        },
        hit_lookup={"EricBalchunas": hit},
        now_dt=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
    )

    assert len(worth_reading) == 1
    assert worth_reading[0]["tweet_url"].endswith("/real_signal")


def test_select_posts_for_report_prefers_informative_posts_over_latest_reply():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="交易盘面/技术分析",
        username="CredibleCrypto",
        role="周期技术分析师",
        category="技术分析 / 周期",
        posts=[
            TweetRecord(
                id="latest_reply",
                text="@andrew658202 Right, wild haha.",
                author_username="CredibleCrypto",
                created_at=datetime(2026, 7, 3, 3, 0, tzinfo=timezone.utc),
                like_count=200,
                retweet_count=5,
                reply_count=8,
                quote_count=0,
            ),
            TweetRecord(
                id="eth_thesis",
                text="ETH is not dead. Sentiment looks similar to the last major bottom and an ETH season can still return from this setup.",
                author_username="CredibleCrypto",
                created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
                like_count=350,
                retweet_count=30,
                reply_count=18,
                quote_count=4,
            ),
        ],
    )

    selected_posts = service._select_posts_for_report(hit)

    assert selected_posts[0].id == "eth_thesis"
    assert all(post.id != "latest_reply" for post in selected_posts)


def test_is_informative_post_filters_pure_emotion_post():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="华语头部大V",
        username="thankUcrypto",
        role="中文交易博主",
        category="交易 / 情绪",
        posts=[],
    )
    post = TweetRecord(
        id="emotion_only",
        text="不是黄金时代 廉价机票 放下手机 相互拥抱吗 怎么特么的还在跌",
        author_username="thankUcrypto",
        created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
        like_count=100,
        retweet_count=5,
        reply_count=2,
        quote_count=0,
    )

    assert service._is_informative_post(post, hit) is False


def test_finalize_ai_output_rewrites_vague_judgement_and_watch_reason():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="宏观 / ETF / DeFi 增量线索",
        username="EricBalchunas",
        role="ETF分析师",
        category="ETF / 机构流向",
        posts=[],
    )
    post = TweetRecord(
        id="etf_signal",
        text="SEC is signaling a more pro-innovation stance toward new ETF structures while trying to avoid copycat filings cutting the line.",
        author_username="EricBalchunas",
        created_at=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
        like_count=300,
        retweet_count=40,
        reply_count=15,
        quote_count=5,
    )

    judgement = service._finalize_judgement("建议继续观察，不要下重结论。", hit, post)
    watch_reason = service._finalize_watch_reason(
        "值得继续跟踪后续是否强化观点。", hit, post
    )

    assert "继续观察" not in judgement
    assert "不要下重结论" not in judgement
    assert "监管" in judgement or "审批" in judgement or "制度" in judgement
    assert "继续观察" not in watch_reason
    assert (
        "审批" in watch_reason
        or "监管" in watch_reason
        or "pro-innovation" in watch_reason
    )


def test_finalize_ai_output_rewrites_generic_empty_judgement_phrase():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="交易盘面/技术分析",
        username="CredibleCrypto",
        role="周期技术分析师",
        category="技术分析 / 周期",
        posts=[],
    )
    post = TweetRecord(
        id="eth_signal",
        text='Yea yea I have been hearing the "ETH is dead" FUD for literally years now and ETH season can still come back.',
        author_username="CredibleCrypto",
        created_at=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
        like_count=300,
        retweet_count=20,
        reply_count=10,
        quote_count=2,
    )

    judgement = service._finalize_judgement(
        "这条内容更像对当前市场结构、机制或叙事方向的定性判断，而不是单纯情绪宣泄。",
        hit,
        post,
    )

    assert "定性判断" not in judgement
    assert "ETH" in judgement
    assert "错杀" in judgement or "反向" in judgement or "衰退" in judgement


def test_build_report_context_excludes_low_signal_accounts_from_body():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    profiles = [
        KolProfile(
            username="CredibleCrypto",
            role="周期技术分析师",
            category="技术分析 / 周期",
            group_name="交易盘面/技术分析",
        ),
        KolProfile(
            username="thankUcrypto",
            role="中文交易博主",
            category="交易 / 情绪",
            group_name="华语头部大V",
        ),
    ]
    informative_hit = KolHit(
        group_name="交易盘面/技术分析",
        username="CredibleCrypto",
        role="周期技术分析师",
        category="技术分析 / 周期",
        posts=[
            TweetRecord(
                id="eth_thesis",
                text="ETH is not dead. Sentiment looks similar to the last major bottom and an ETH season can still return from this setup.",
                author_username="CredibleCrypto",
                created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
                like_count=350,
                retweet_count=30,
                reply_count=18,
                quote_count=4,
            ),
        ],
    )
    low_signal_hit = KolHit(
        group_name="华语头部大V",
        username="thankUcrypto",
        role="中文交易博主",
        category="交易 / 情绪",
        posts=[
            TweetRecord(
                id="emotion_only",
                text="不是黄金时代 廉价机票 放下手机 相互拥抱吗 怎么特么的还在跌",
                author_username="thankUcrypto",
                created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
                like_count=100,
                retweet_count=5,
                reply_count=2,
                quote_count=0,
            ),
        ],
    )

    context = service._build_report_context(
        title="2026-07-03 加密KOL过去24小时监控报告",
        start_dt=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
        end_dt=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        now_dt=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        profiles=profiles,
        hits=[informative_hit, low_signal_hit],
        fetched_accounts=["CredibleCrypto", "thankUcrypto"],
        no_post_accounts=[],
        fetch_error_accounts=[],
    )

    rendered_usernames = {
        item["username"] for group in context["groups"] for item in group["hits"]
    }
    worth_reading_usernames = {
        item["display_name"].lstrip("@") for item in context["worth_reading"]
    }
    focus_usernames = {item["username"] for item in context["focus_accounts"]}

    assert context["hit_count"] == 1
    assert "CredibleCrypto" in rendered_usernames
    assert "thankUcrypto" not in rendered_usernames
    assert "thankUcrypto" not in worth_reading_usernames
    assert "thankUcrypto" not in focus_usernames
    assert "thankUcrypto" in context["low_signal_accounts"]


def test_build_focus_accounts_uses_investor_useful_reason():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="宏观 / ETF / DeFi 增量线索",
        username="MonetSupply",
        role="稳定币研究员",
        category="稳定币 / 收益",
        posts=[
            TweetRecord(
                id="yield_signal",
                text="Spark Savings on RobinhoodApp chain shows that stablecoin yield products compete on execution, atomic liquidity, and user experience rather than APY alone.",
                author_username="MonetSupply",
                created_at=datetime(2026, 7, 3, 1, 0, tzinfo=timezone.utc),
                like_count=120,
                retweet_count=10,
                reply_count=5,
                quote_count=1,
            )
        ],
    )

    focus_accounts = service._build_focus_accounts(
        ai_payload=None,
        hit_lookup={"MonetSupply": hit},
        worth_reading=[
            {
                "display_name": "@MonetSupply",
                "tweet_url": "https://x.com/MonetSupply/status/yield_signal",
                "tags": ["#KOL/MonetSupply", "#Topic/Stablecoin"],
            }
        ],
    )

    assert len(focus_accounts) == 1
    assert (
        "稳定币" in focus_accounts[0]["reason"]
        or "收益产品化" in focus_accounts[0]["reason"]
    )


def test_align_group_worth_reading_links_keeps_only_selected_urls():
    service = KolService.__new__(KolService)
    groups = [
        {
            "group_name": "交易盘面/技术分析",
            "hits": [
                {
                    "username": "CredibleCrypto",
                    "tweet_url": "https://x.com/CredibleCrypto/status/1",
                },
                {
                    "username": "RektCapital",
                    "tweet_url": "https://x.com/rektcapital/status/2",
                },
            ],
        }
    ]
    worth_reading = [
        {
            "display_name": "@CredibleCrypto",
            "tweet_url": "https://x.com/CredibleCrypto/status/1",
            "tags": [],
        }
    ]

    service._align_group_worth_reading_links(groups, worth_reading)

    assert groups[0]["hits"][0]["tweet_url"].endswith("/1")
    assert groups[0]["hits"][1]["tweet_url"] == ""


def test_is_informative_post_filters_generic_market_chatter_without_crypto_anchor():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="华语头部大V",
        username="thankUcrypto",
        role="中文交易博主",
        category="交易 / 情绪",
        posts=[],
    )
    post = TweetRecord(
        id="stock_leverage",
        text="海力士成本我记得是1400 闪迪1750 美光975 加起来4倍杠杆 下周见。",
        author_username="thankUcrypto",
        created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
        like_count=80,
        retweet_count=3,
        reply_count=2,
        quote_count=0,
    )

    assert service._is_informative_post(post, hit) is False


def test_is_informative_post_filters_offtopic_social_commentary():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="华语优质海外博主",
        username="0xTodd",
        role="海外华人链上分析师",
        category="华语 / 链上数据",
        posts=[],
    )
    post = TweetRecord(
        id="offtopic",
        text="这个号最近的推文除了 PM 操纵民主之外，还包括平行国家实验、爱泼斯坦和 Paypal 黑帮掌握比特币、CIA 控制疫苗、AI 真相法庭篡夺叙事。",
        author_username="0xTodd",
        created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
        like_count=120,
        retweet_count=10,
        reply_count=8,
        quote_count=1,
    )

    assert service._is_informative_post(post, hit) is False


def test_is_informative_post_filters_generic_protocol_marketing():
    service = KolService.__new__(KolService)
    service.settings = SimpleNamespace(timezone="Asia/Shanghai")
    service.deepseek = DummyDeepSeek()
    service.logger = object()

    hit = KolHit(
        group_name="海外权威创始&机构大佬",
        username="justinsuntron",
        role="TRON创始人",
        category="公链 / 交易平台 / 行业话题",
        posts=[],
    )
    post = TweetRecord(
        id="promo",
        text="Interesting direction. Payments should be more flexible, more global, and closer to real time. TRON is built for this kind of scale.",
        author_username="justinsuntron",
        created_at=datetime(2026, 7, 3, 2, 0, tzinfo=timezone.utc),
        like_count=90,
        retweet_count=6,
        reply_count=4,
        quote_count=0,
    )

    assert service._is_informative_post(post, hit) is False
