from app.clients.deepseek_client import DeepSeekClient


def test_parse_json_content_handles_fenced_block():
    content = """```json
    {"ok": true, "value": "hello"}
    ```"""

    parsed = DeepSeekClient._parse_json_content(content)

    assert parsed == {"ok": True, "value": "hello"}


def test_parse_json_content_extracts_wrapped_json():
    content = 'result: {"items": [1, 2, 3]} done'

    parsed = DeepSeekClient._parse_json_content(content)

    assert parsed == {"items": [1, 2, 3]}
