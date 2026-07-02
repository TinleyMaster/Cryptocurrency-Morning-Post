from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.clients.feishu_client import FeishuClient
from app.clients.wecom_client import WeComClient
from app.clients.xpoz_client import XpozClient
from app.logger import log_event
from app.models.kol import KolProfile
from app.models.tweet import KolHit
from app.renderers.kol_renderer import KolRenderer
from app.services.base_archive_service import BaseArchiveService
from app.services.deepread_service import DeepreadService
from app.services.feishu_publish_service import FeishuPublishService
from app.utils.file_utils import write_utf8
from app.utils.time_utils import (
    get_last_24h_window,
    is_in_last_24h,
    now_in_timezone,
    report_date_str,
)


class KolService:
    def __init__(self, settings, logger) -> None:
        self.settings = settings
        self.logger = logger
        self.renderer = KolRenderer()
        self.xpoz = XpozClient(settings.env.get("XPOZ_API_KEY"))
        self.publisher = FeishuPublishService(
            FeishuClient(
                settings.env.get("FEISHU_APP_ID"), settings.env.get("FEISHU_APP_SECRET")
            ),
            settings.feishu,
        )
        self.wecom = WeComClient(settings.env.get("WECOM_BOT_WEBHOOK_URL"))
        self.deepread_service = DeepreadService(self.xpoz)
        self.base_archive_service = BaseArchiveService()

    def load_kols(self) -> list[KolProfile]:
        profiles: list[KolProfile] = []
        for group in self.settings.kols.get("groups", []):
            for member in group.get("members", []):
                if member.get("enabled", True):
                    profiles.append(
                        KolProfile(group_name=group["group_name"], **member)
                    )
        return profiles

    def run_daily_report(self) -> dict[str, Any]:
        now_dt = now_in_timezone(self.settings.timezone)
        start_dt, end_dt = get_last_24h_window(now_dt)
        hits: list[KolHit] = []
        for profile in self.load_kols():
            posts = [
                post
                for post in self.xpoz.get_recent_posts_by_author(profile.username)
                if is_in_last_24h(post.created_at, now_dt)
            ]
            if posts:
                hits.append(
                    KolHit(
                        group_name=profile.group_name,
                        username=profile.username,
                        role=profile.role,
                        category=profile.category,
                        posts=posts,
                    )
                )

        grouped = []
        worth_reading = []
        for hit in hits:
            primary_post = hit.posts[0]
            grouped.append(
                {
                    "group_name": hit.group_name,
                    "group_summary": f"当前样例数据下，这一组主要围绕 {hit.category} 展开讨论。",
                    "hits": [
                        {
                            "username": hit.username,
                            "role": hit.role,
                            "core": primary_post.text,
                            "judgement": "先不追涨，优先确认叙事是否持续、是否具备边际增量。",
                            "watch_reason": "这里是样例总结占位，后续应替换为基于真实帖文内容的判断。",
                        }
                    ],
                }
            )
            worth_reading.append(
                {
                    "display_name": f"@{hit.username}",
                    "tweet_url": f"https://x.com/{hit.username}/status/{primary_post.id}",
                    "tags": [
                        f"#KOL/{hit.username}",
                        "#Topic/BTC",
                        "#Type/MarketFramework",
                        f"#Date/{report_date_str(now_dt)}",
                    ],
                }
            )

        title = f"{report_date_str(now_dt)} 加密KOL过去24小时监控报告"
        markdown = self.renderer.render_report(
            {
                "title": title,
                "window_start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "window_end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": self.settings.timezone,
                "hit_count": len(hits),
                "post_count": sum(len(hit.posts) for hit in hits),
                "one_liner": "今天更像是机构框架与风险偏好修复的交叉验证日，而不是全面风险回归日。",
                "groups": grouped,
                "worth_reading": worth_reading,
            }
        )
        report_path = Path(self.settings.output_dirs["kol_dir"]) / f"{title}.md"
        write_utf8(report_path, markdown)

        deepread_title = f"{report_date_str(now_dt)} 值得一读推文原文与逻辑拆解"
        tweets = self.deepread_service.build_tweets(
            markdown, report_date=report_date_str(now_dt)
        )
        deepread_markdown = self.deepread_service.render(deepread_title, title, tweets)
        deepread_path = (
            Path(self.settings.output_dirs["deepread_dir"]) / f"{deepread_title}.md"
        )
        write_utf8(deepread_path, deepread_markdown)

        payload = self.base_archive_service.build_payload(tweets, now_dt)
        payload_path = (
            Path(self.settings.output_dirs["base_payload_dir"])
            / f"worth_reading_tweets_batch_{report_date_str(now_dt)}.json"
        )
        write_utf8(payload_path, json.dumps(payload, ensure_ascii=False, indent=2))

        doc_url = ""
        doc_note = ""
        message_id = ""
        wecom_status = ""
        record_ids: list[str] = []
        doc_import_blocker = self.publisher.get_doc_import_blocker()
        if doc_import_blocker:
            doc_note = f"未生成（{doc_import_blocker}）"
            log_event(
                self.logger,
                job="kol_report",
                stage="feishu_doc_import",
                status="skipped",
                detail=doc_import_blocker,
            )
        else:
            try:
                doc_url = self.publisher.import_markdown_as_docx(report_path, title)
            except Exception as exc:
                doc_note = f"未生成（导入失败：{exc}）"
                log_event(
                    self.logger,
                    job="kol_report",
                    stage="feishu_doc_import",
                    status="warning",
                    detail=str(exc),
                )

        summary_markdown = self._build_summary_markdown(
            title=title,
            hit_count=len(hits),
            post_count=sum(len(hit.posts) for hit in hits),
            record_count=len(payload.get("rows", [])),
            doc_url=doc_url,
            doc_note=doc_note,
        )
        if self.publisher.can_send_summary():
            message_id = self.publisher.send_summary(title=title, content=summary_markdown)
        if self.wecom.has_webhook():
            try:
                wecom_status = self.wecom.send_webhook_markdown_message(
                    title=title,
                    markdown=summary_markdown,
                )
            except Exception as exc:
                log_event(
                    self.logger,
                    job="kol_report",
                    stage="wecom_summary",
                    status="warning",
                    detail=str(exc),
                )
        if self.publisher.can_write_base_records():
            record_ids = self.publisher.batch_create_base_records(payload)
        log_event(
            self.logger,
            job="kol_report",
            stage="publish",
            status="success",
            doc_url=doc_url,
            doc_note=doc_note,
            records=len(record_ids),
            message_id=message_id,
            wecom_status=wecom_status,
        )
        return {
            "report_path": report_path,
            "deepread_path": deepread_path,
            "payload_path": payload_path,
            "doc_url": doc_url,
            "message_id": message_id,
            "wecom_status": wecom_status,
            "record_ids": record_ids,
        }

    def _build_summary_markdown(
        self,
        title: str,
        hit_count: int,
        post_count: int,
        record_count: int,
        doc_url: str,
        doc_note: str,
    ) -> str:
        lines = [
            "今日加密 KOL 过去 24 小时监控报告已更新：",
            "",
            f"- 标题：{title}",
            f"- 命中账号：{hit_count}",
            f"- 有效帖子：{post_count}",
            f"- Base 归档：{record_count} 条",
        ]
        if doc_url:
            lines.append(f"- 云文档：{doc_url}")
        elif doc_note:
            lines.append(f"- 云文档：{doc_note}")
        return "\n".join(lines)
