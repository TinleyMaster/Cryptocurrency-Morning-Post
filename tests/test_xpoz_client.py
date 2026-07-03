from datetime import datetime

from app.clients.xpoz_client import XpozClient


class FakeTwitterPost:
    def __init__(
        self,
        post_id: str,
        text: str,
        author_username: str,
        created_at_date: str,
        created_at: str | None = None,
        like_count: int = 0,
        retweet_count: int = 0,
        reply_count: int = 0,
        quote_count: int = 0,
    ) -> None:
        self.id = post_id
        self.text = text
        self.author_username = author_username
        self.created_at_date = created_at_date
        self.like_count = like_count
        self.retweet_count = retweet_count
        self.reply_count = reply_count
        self.quote_count = quote_count
        self.created_at = created_at


class FakePaginatedResult:
    def __init__(self, data):
        self.data = data


class FakeTwitterNamespace:
    def get_posts_by_author(self, identifier, **kwargs):  # noqa: ANN001
        return FakePaginatedResult(
            [
                FakeTwitterPost(
                    "1",
                    "post-text",
                    identifier,
                    "2026-06-30T00:00:00.000Z",
                    created_at="2026-06-30T08:30:00.000Z",
                    like_count=10,
                    retweet_count=2,
                    reply_count=3,
                    quote_count=1,
                )
            ]
        )

    def get_posts_by_ids(self, post_ids, **kwargs):  # noqa: ANN001
        return [
            FakeTwitterPost(
                post_ids[0],
                "hydrated-post",
                "saylor",
                "2026-06-30",
                like_count=20,
                retweet_count=4,
                reply_count=5,
                quote_count=2,
            )
        ]


class FakeSdkClient:
    def __init__(self) -> None:
        self.twitter = FakeTwitterNamespace()

    def close(self) -> None:
        return None


def test_xpoz_client_maps_sdk_result(monkeypatch):
    client = XpozClient(api_key="dummy")
    monkeypatch.setattr(client, "_get_sdk_client", lambda: FakeSdkClient())

    posts = client.get_recent_posts_by_author("saylor")
    hydrated = client.get_posts_by_ids(["1"])

    assert posts[0].author_username == "saylor"
    assert posts[0].like_count == 10
    assert isinstance(posts[0].created_at, datetime)
    assert posts[0].created_at.tzinfo is not None
    assert posts[0].created_at_precision == "datetime"
    assert hydrated[0].text == "hydrated-post"
    assert hydrated[0].quote_count == 2
    assert hydrated[0].created_at.tzinfo is not None
    assert hydrated[0].created_at_precision == "date"
