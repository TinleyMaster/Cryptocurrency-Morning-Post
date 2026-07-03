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
