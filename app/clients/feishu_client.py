from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import requests


class FeishuClient:
    BASE_URL = "https://open.feishu.cn"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.timeout = timeout
        self._tenant_access_token: str | None = None
        self._tenant_access_token_expire_at = 0.0

    def has_app_credentials(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def import_markdown_as_docx(
        self,
        file_path: str | Path,
        title: str,
        folder_token: str,
        poll_interval: float = 1.5,
        poll_timeout: int = 120,
    ) -> str:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Feishu import source file not found: {file_path}")
        if not folder_token:
            raise ValueError("folder_token is required for Feishu doc import.")

        file_token = self._upload_import_media(file_path=file_path, target_type="docx")
        ticket = self._create_import_task(
            file_token=file_token,
            file_name=title,
            file_extension=file_path.suffix.lstrip(".") or "md",
            mount_key=folder_token,
            target_type="docx",
        )
        return self._poll_import_task(
            ticket, poll_interval=poll_interval, poll_timeout=poll_timeout
        )

    @staticmethod
    def build_post_content(title: str, markdown: str, locale: str = "zh_cn") -> str:
        payload = {
            locale: {
                "title": title,
                "content": [[{"tag": "md", "text": markdown}]],
            }
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def send_rich_text_message(self, chat_id: str, title: str, markdown: str) -> str:
        if not chat_id:
            raise ValueError("chat_id is required for sending Feishu message.")

        payload = {
            "receive_id": chat_id,
            "msg_type": "post",
            "content": self.build_post_content(title=title, markdown=markdown),
        }
        response = self._request(
            "POST",
            "/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            json_body=payload,
        )
        return response["data"]["message_id"]

    @staticmethod
    def build_webhook_text_content(title: str, markdown: str) -> dict[str, Any]:
        return {
            "msg_type": "text",
            "content": {"text": f"{title}\n\n{markdown}"},
        }

    def send_webhook_text_message(
        self, webhook_url: str, title: str, markdown: str
    ) -> str:
        if not webhook_url:
            raise ValueError("webhook_url is required for Feishu webhook message.")

        session = requests.Session()
        session.trust_env = False
        response = session.post(
            webhook_url,
            headers={"Content-Type": "application/json; charset=utf-8"},
            json=self.build_webhook_text_content(title=title, markdown=markdown),
            timeout=self.timeout,
        )
        payload = self._parse_response(response)
        return payload.get("msg", "ok")

    def batch_create_base_records(
        self,
        base_token: str,
        table_id: str,
        payload: dict,
    ) -> list[str]:
        if not base_token or not table_id:
            raise ValueError(
                "base_token and table_id are required for Base batch create."
            )

        records = [{"fields": row} for row in payload.get("rows", [])]
        if not records:
            return []

        response = self._request(
            "POST",
            f"/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records/batch_create",
            json_body={
                "records": records,
                "client_token": str(uuid.uuid4()),
            },
        )

        items = response.get("data", {}).get("records", [])
        if items:
            return [item["record_id"] for item in items]
        return response.get("data", {}).get("record_ids", [])

    def _upload_import_media(self, file_path: Path, target_type: str) -> str:
        access_token = self._get_tenant_access_token()
        url = f"{self.BASE_URL}/open-apis/drive/v1/medias/upload_all"
        file_extension = file_path.suffix.lstrip(".") or "md"
        extra = json.dumps(
            {"obj_type": target_type, "file_extension": file_extension},
            ensure_ascii=False,
            separators=(",", ":"),
        )

        with file_path.open("rb") as fh:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                data={
                    "file_name": file_path.name,
                    "parent_type": "ccm_import_open",
                    "size": str(file_path.stat().st_size),
                    "extra": extra,
                },
                files={"file": (file_path.name, fh, "text/markdown; charset=utf-8")},
                timeout=self.timeout,
            )

        result = self._parse_response(response)
        # #region debug-point B:upload-media
        try:
            import json as _dbg_json, urllib.request as _dbg_urllib_request

            _p = ".dbg/feishu-publish-missing.env"
            _u, _s = "http://127.0.0.1:17877/event", "feishu-publish-missing"
            exec(
                "try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept: pass"
            )
            _dbg_urllib_request.urlopen(
                _dbg_urllib_request.Request(
                    _u,
                    data=_dbg_json.dumps(
                        {
                            "sessionId": _s,
                            "runId": "pre-fix",
                            "hypothesisId": "B",
                            "location": "feishu_client.py:133",
                            "msg": "[DEBUG] feishu media uploaded",
                            "data": {
                                "status_code": response.status_code,
                                "file_name": file_path.name,
                            },
                        },
                        ensure_ascii=False,
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
            ).read()
        except Exception:
            pass
        # #endregion
        return result["data"]["file_token"]

    def _create_import_task(
        self,
        file_token: str,
        file_name: str,
        file_extension: str,
        mount_key: str,
        target_type: str,
    ) -> str:
        response = self._request(
            "POST",
            "/open-apis/drive/v1/import_tasks",
            json_body={
                "file_extension": file_extension,
                "file_token": file_token,
                "type": target_type,
                "file_name": file_name,
                "point": {
                    "mount_type": 1,
                    "mount_key": mount_key,
                },
            },
        )
        return response["data"]["ticket"]

    def _poll_import_task(
        self,
        ticket: str,
        poll_interval: float,
        poll_timeout: int,
    ) -> str:
        deadline = time.time() + poll_timeout
        last_result: dict[str, Any] | None = None
        while time.time() < deadline:
            response = self._request(
                "GET", f"/open-apis/drive/v1/import_tasks/{ticket}"
            )
            result = response.get("data", {}).get("result", {})
            last_result = result
            # #region debug-point B:poll-import-result
            try:
                import json as _dbg_json, urllib.request as _dbg_urllib_request

                _p = ".dbg/feishu-publish-missing.env"
                _u, _s = "http://127.0.0.1:17877/event", "feishu-publish-missing"
                exec(
                    "try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept: pass"
                )
                _dbg_urllib_request.urlopen(
                    _dbg_urllib_request.Request(
                        _u,
                        data=_dbg_json.dumps(
                            {
                                "sessionId": _s,
                                "runId": "pre-fix",
                                "hypothesisId": "B",
                                "location": "feishu_client.py:177",
                                "msg": "[DEBUG] feishu import poll result",
                                "data": {
                                    "ticket": ticket,
                                    "job_status": result.get("job_status"),
                                    "job_error_msg": result.get("job_error_msg"),
                                    "has_url": bool(result.get("url")),
                                    "result_keys": list(result.keys()),
                                },
                            },
                            ensure_ascii=False,
                        ).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                ).read()
            except Exception:
                pass
            # #endregion
            if result.get("url"):
                return result["url"]

            job_status = result.get("job_status")
            error_msg = (result.get("job_error_msg") or "").strip()
            if error_msg and error_msg.lower() != "success":
                raise RuntimeError(
                    "Feishu import task failed: "
                    f"status={job_status}, error={error_msg}, result={result}, response={response}"
                )

            time.sleep(poll_interval)

        raise TimeoutError(f"Feishu import task timed out: {last_result}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        access_token = self._get_tenant_access_token()
        response = requests.request(
            method,
            f"{self.BASE_URL}{path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            params=params,
            json=json_body,
            timeout=self.timeout,
        )
        # #region debug-point D:feishu-request
        try:
            import json as _dbg_json, urllib.request as _dbg_urllib_request

            _p = ".dbg/feishu-publish-missing.env"
            _u, _s = "http://127.0.0.1:17877/event", "feishu-publish-missing"
            exec(
                "try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept: pass"
            )
            _dbg_urllib_request.urlopen(
                _dbg_urllib_request.Request(
                    _u,
                    data=_dbg_json.dumps(
                        {
                            "sessionId": _s,
                            "runId": "pre-fix",
                            "hypothesisId": "D",
                            "location": "feishu_client.py:205",
                            "msg": "[DEBUG] feishu request completed",
                            "data": {
                                "method": method,
                                "path": path,
                                "status_code": response.status_code,
                            },
                        },
                        ensure_ascii=False,
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
            ).read()
        except Exception:
            pass
        # #endregion
        return self._parse_response(response)

    def _get_tenant_access_token(self) -> str:
        self._ensure_credentials()

        now = time.time()
        if self._tenant_access_token and now < self._tenant_access_token_expire_at:
            return self._tenant_access_token

        response = requests.post(
            f"{self.BASE_URL}/open-apis/auth/v3/tenant_access_token/internal",
            headers={"Content-Type": "application/json; charset=utf-8"},
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=self.timeout,
        )
        data = self._parse_response(response)
        # #region debug-point E:token-response
        try:
            import json as _dbg_json, urllib.request as _dbg_urllib_request

            _p = ".dbg/feishu-publish-missing.env"
            _u, _s = "http://127.0.0.1:17877/event", "feishu-publish-missing"
            exec(
                "try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept: pass"
            )
            _dbg_urllib_request.urlopen(
                _dbg_urllib_request.Request(
                    _u,
                    data=_dbg_json.dumps(
                        {
                            "sessionId": _s,
                            "runId": "pre-fix",
                            "hypothesisId": "E",
                            "location": "feishu_client.py:223",
                            "msg": "[DEBUG] tenant token fetched",
                            "data": {
                                "status_code": response.status_code,
                                "has_token": bool(data.get("tenant_access_token")),
                            },
                        },
                        ensure_ascii=False,
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
            ).read()
        except Exception:
            pass
        # #endregion
        self._tenant_access_token = data["tenant_access_token"]
        expire_seconds = int(data.get("expire", 7200))
        self._tenant_access_token_expire_at = now + max(expire_seconds - 300, 60)
        return self._tenant_access_token

    def _parse_response(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Feishu API returned non-JSON response: {response.status_code} {response.text}"
            ) from exc

        if response.status_code >= 400 or payload.get("code", 0) != 0:
            # #region debug-point D:feishu-error
            try:
                import json as _dbg_json, urllib.request as _dbg_urllib_request

                _p = ".dbg/feishu-publish-missing.env"
                _u, _s = "http://127.0.0.1:17877/event", "feishu-publish-missing"
                exec(
                    "try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept: pass"
                )
                _dbg_urllib_request.urlopen(
                    _dbg_urllib_request.Request(
                        _u,
                        data=_dbg_json.dumps(
                            {
                                "sessionId": _s,
                                "runId": "pre-fix",
                                "hypothesisId": "D",
                                "location": "feishu_client.py:240",
                                "msg": "[DEBUG] feishu request failed",
                                "data": {
                                    "status_code": response.status_code,
                                    "code": payload.get("code"),
                                    "msg": payload.get("msg"),
                                },
                            },
                            ensure_ascii=False,
                        ).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                ).read()
            except Exception:
                pass
            # #endregion
            raise RuntimeError(
                "Feishu API request failed: "
                f"status={response.status_code}, code={payload.get('code')}, "
                f"msg={payload.get('msg')}, response={payload}"
            )
        return payload

    def _ensure_credentials(self) -> None:
        if not self.app_id or not self.app_secret:
            raise RuntimeError(
                "FEISHU_APP_ID and FEISHU_APP_SECRET must be configured before calling Feishu APIs."
            )
