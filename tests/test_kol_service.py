from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.kol import KolProfile
from app.models.tweet import KolHit, TweetRecord
from app.services.kol_service import KolService


class DummyPublisher:
    def __init__(self, blocker: str | None = None, exc: Exception | None = None) -> None:
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
    service.publisher = DummyPublisher(blocker="缺少 FEISHU_BASE_TOKEN / FEISHU_TABLE_ID")
    service.logger = object()
    events: list[dict] = []

    monkeypatch.setattr("app.services.kol_service.log_event", lambda logger, **kwargs: events.append(kwargs))

    record_ids, note = service._archive_base_records({"rows": [{"tweet_id": "1"}]})

    assert record_ids == []
    assert note == "未执行（缺少 FEISHU_BASE_TOKEN / FEISHU_TABLE_ID）"
    assert events[0]["stage"] == "feishu_base_archive"
    assert events[0]["status"] == "skipped"


def test_archive_base_records_downgrades_exception(monkeypatch):
    service = KolService.__new__(KolService)
    service.publisher = DummyPublisher(exc=RuntimeError("Feishu API request failed: status=400, code=91402, msg=NOTEXIST"))
    service.logger = object()
    events: list[dict] = []

    monkeypatch.setattr("app.services.kol_service.log_event", lambda logger, **kwargs: events.append(kwargs))

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
