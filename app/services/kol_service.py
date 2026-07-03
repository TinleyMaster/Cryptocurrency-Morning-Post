from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.clients.deepseek_client import DeepSeekClient
from app.clients.feishu_client import FeishuClient
from app.clients.wecom_client import WeComClient
from app.clients.xpoz_client import XpozClient
from app.logger import log_event
from app.models.kol import KolProfile
from app.models.tweet import KolHit, TweetRecord
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
    DEFAULT_FETCH_LIMIT_PER_AUTHOR = 40
    MAX_WORTH_READING_ITEMS = 15
    MAX_WORTH_READING_PER_AUTHOR = 2
    MIN_INFORMATIVE_POST_SCORE = 180
    MIN_REPORT_POSTS_PER_AUTHOR = 4

    def __init__(self, settings, logger) -> None:
        self.settings = settings
        self.logger = logger
        self.renderer = KolRenderer()
        self.xpoz = XpozClient(settings.env.get("XPOZ_API_KEY"))
        self.deepseek = DeepSeekClient(
            settings.env.get("DEEPSEEK_API_KEY"),
            base_url=settings.env.get("DEEPSEEK_BASE_URL"),
            model=settings.env.get("DEEPSEEK_MODEL"),
        )
        self.publisher = FeishuPublishService(
            FeishuClient(
                settings.env.get("FEISHU_APP_ID"), settings.env.get("FEISHU_APP_SECRET")
            ),
            settings.feishu,
        )
        self.wecom = WeComClient(settings.env.get("WECOM_BOT_WEBHOOK_URL"))
        self.deepread_service = DeepreadService(self.xpoz, self.deepseek, logger)
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
        profiles = self.load_kols()

        hits: list[KolHit] = []
        fetched_accounts: list[str] = []
        no_post_accounts: list[str] = []
        fetch_error_accounts: list[str] = []

        for profile in profiles:
            try:
                posts = self.xpoz.get_recent_posts_by_author(
                    profile.username, limit=self.DEFAULT_FETCH_LIMIT_PER_AUTHOR
                )
            except Exception as exc:
                fetch_error_accounts.append(profile.username)
                log_event(
                    self.logger,
                    job="kol_report",
                    stage="fetch_author_posts",
                    status="warning",
                    username=profile.username,
                    detail=str(exc),
                )
                continue

            fetched_accounts.append(profile.username)
            recent_posts = sorted(
                [
                    post
                    for post in posts
                    if is_in_last_24h(post.created_at, now_dt)
                    and (post.text or "").strip()
                ],
                key=lambda item: item.created_at,
                reverse=True,
            )
            if recent_posts:
                hits.append(
                    KolHit(
                        group_name=profile.group_name,
                        username=profile.username,
                        role=profile.role,
                        category=profile.category,
                        posts=recent_posts,
                    )
                )
            else:
                no_post_accounts.append(profile.username)

        title = f"{report_date_str(now_dt)} 加密KOL过去24小时监控报告"
        context = self._build_report_context(
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            now_dt=now_dt,
            profiles=profiles,
            hits=hits,
            fetched_accounts=fetched_accounts,
            no_post_accounts=no_post_accounts,
            fetch_error_accounts=fetch_error_accounts,
        )
        markdown = self.renderer.render_report(context)
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
        base_note = ""
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

        record_ids, base_note = self._archive_base_records(payload)
        summary_markdown = self._build_summary_markdown(
            title=title,
            hit_count=len(hits),
            post_count=sum(len(hit.posts) for hit in hits),
            record_count=len(record_ids),
            base_note=base_note,
            doc_url=doc_url,
            doc_note=doc_note,
            one_liner=context["one_liner"],
            worth_reading_count=len(context["worth_reading"]),
        )
        if self.publisher.can_send_summary():
            message_id = self.publisher.send_summary(
                title=title, content=summary_markdown
            )
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
        log_event(
            self.logger,
            job="kol_report",
            stage="publish",
            status="success",
            doc_url=doc_url,
            doc_note=doc_note,
            base_note=base_note,
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

    def _build_report_context(
        self,
        *,
        title: str,
        start_dt,
        end_dt,
        now_dt,
        profiles: list[KolProfile],
        hits: list[KolHit],
        fetched_accounts: list[str],
        no_post_accounts: list[str],
        fetch_error_accounts: list[str],
    ) -> dict[str, Any]:
        total_accounts = len(profiles)
        post_count = sum(len(hit.posts) for hit in hits)
        report_date = report_date_str(now_dt)
        hit_lookup = {hit.username: hit for hit in hits}
        grouped_hits = self._group_hits(hits)
        ai_payload: dict[str, Any] | None = None

        if hits and self.deepseek.is_configured():
            try:
                ai_payload = self.deepseek.generate_json(
                    system_prompt=self._report_system_prompt(),
                    user_prompt=self._report_user_prompt(
                        title=title,
                        start_dt=start_dt,
                        end_dt=end_dt,
                        total_accounts=total_accounts,
                        fetched_accounts=len(fetched_accounts),
                        hits=hits,
                    ),
                    temperature=0.2,
                    max_tokens=4200,
                )
            except Exception as exc:
                log_event(
                    self.logger,
                    job="kol_report",
                    stage="deepseek_report",
                    status="warning",
                    detail=str(exc),
                )

        groups, rendered_usernames = self._build_groups(
            ai_payload=ai_payload,
            grouped_hits=grouped_hits,
            hit_lookup=hit_lookup,
            now_dt=now_dt,
        )
        worth_reading = self._build_worth_reading(ai_payload, hit_lookup, now_dt)
        focus_accounts = self._build_focus_accounts(
            ai_payload, hit_lookup, worth_reading
        )

        low_signal_accounts = sorted(
            username for username in hit_lookup if username not in rendered_usernames
        )
        overview = self._safe_list(ai_payload.get("overview") if ai_payload else None)
        if not overview:
            overview = [
                f"本次配置追踪 `{total_accounts}` 个账号，其中成功拉取 `{len(fetched_accounts)}` 个。",
                f"过去 24 小时命中 `{len(hits)}` 个账号，约 `{post_count}` 条帖子。",
                f"高频主题主要集中在：{self._topics_overview(hits)}。",
            ]

        three_points = self._safe_list(
            ai_payload.get("three_points") if ai_payload else None
        )
        if not three_points:
            three_points = self._fallback_three_points(hits)

        consensus = self._safe_list(ai_payload.get("consensus") if ai_payload else None)
        if not consensus:
            consensus = self._fallback_consensus(hits)

        differences = self._safe_list(
            ai_payload.get("differences") if ai_payload else None
        )
        if not differences:
            differences = self._fallback_differences(hits)

        one_liner = self._safe_text(
            ai_payload.get("one_liner") if ai_payload else None,
            "今天更像是多条结构性叙事并行发酵的一天，而不是单一方向的全面共识。",
        )

        return {
            "title": title,
            "window_start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "window_end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": self.settings.timezone,
            "total_accounts": total_accounts,
            "fetched_accounts": len(fetched_accounts),
            "hit_count": len(hits),
            "post_count": post_count,
            "one_liner": one_liner,
            "three_points": three_points,
            "overview": overview,
            "groups": groups,
            "consensus": consensus,
            "differences": differences,
            "focus_accounts": focus_accounts,
            "worth_reading": worth_reading,
            "no_post_accounts": sorted(no_post_accounts),
            "low_signal_accounts": low_signal_accounts,
            "fetch_error_accounts": sorted(fetch_error_accounts),
            "report_date": report_date,
        }

    def _build_groups(
        self,
        *,
        ai_payload: dict[str, Any] | None,
        grouped_hits: dict[str, list[KolHit]],
        hit_lookup: dict[str, KolHit],
        now_dt,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        groups: list[dict[str, Any]] = []
        rendered_usernames: set[str] = set()
        ai_groups = ai_payload.get("groups") if ai_payload else None

        if isinstance(ai_groups, list):
            for ai_group in ai_groups:
                if not isinstance(ai_group, dict):
                    continue
                candidates = ai_group.get("authors") or ai_group.get("hits") or []
                rendered_hits = []
                resolved_group_name = self._safe_text(ai_group.get("group_name"))
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    username = self._normalize_username(candidate.get("username"))
                    hit = hit_lookup.get(username)
                    if not hit or username in rendered_usernames:
                        continue
                    post = self._pick_informative_post(hit, candidate.get("tweet_id"))
                    rendered_hits.append(
                        self._render_hit_block(
                            hit=hit,
                            post=post,
                            now_dt=now_dt,
                            core=self._safe_text(
                                candidate.get("core"),
                                self._summarize_text(post.text, 140),
                            ),
                            judgement=self._safe_text(
                                candidate.get("judgement"),
                                "当前更适合把它当作线索，而不是单条推文就下重结论。",
                            ),
                            watch_reason=self._safe_text(
                                candidate.get("watch_reason"),
                                "值得继续跟踪这位账号后续 1-2 天是否持续强化同一叙事。",
                            ),
                            tags=self._normalize_tags(
                                candidate.get("tags"), hit, post, now_dt
                            ),
                        )
                    )
                    rendered_usernames.add(username)
                    if not resolved_group_name:
                        resolved_group_name = hit.group_name

                if rendered_hits:
                    groups.append(
                        {
                            "group_name": resolved_group_name
                            or rendered_hits[0]["group_name"],
                            "group_summary": self._safe_text(
                                ai_group.get("group_summary"),
                                self._fallback_group_summary(
                                    resolved_group_name
                                    or rendered_hits[0]["group_name"],
                                    [
                                        hit_lookup[item["username"]]
                                        for item in rendered_hits
                                    ],
                                ),
                            ),
                            "hits": rendered_hits,
                        }
                    )

        if groups:
            return groups, rendered_usernames

        fallback_groups: list[dict[str, Any]] = []
        for group_name, group_hits in grouped_hits.items():
            sorted_hits = sorted(group_hits, key=self._hit_signal_score, reverse=True)
            selected_hits = sorted_hits[:4]
            rendered_hits = [
                self._render_hit_block(
                    hit=hit,
                    post=hit.posts[0],
                    now_dt=now_dt,
                    core=self._summarize_text(hit.posts[0].text, 140),
                    judgement="当前更适合把它当作线索跟踪，而不是只靠单条表达直接追价。",
                    watch_reason="建议继续观察是否出现连续发帖、互动放大或观点强化。",
                    tags=self._infer_tags(hit, hit.posts[0], now_dt),
                )
                for hit in selected_hits
            ]
            rendered_usernames.update(hit.username for hit in selected_hits)
            fallback_groups.append(
                {
                    "group_name": group_name,
                    "group_summary": self._fallback_group_summary(
                        group_name, selected_hits
                    ),
                    "hits": rendered_hits,
                }
            )
        return fallback_groups, rendered_usernames

    def _build_worth_reading(
        self,
        ai_payload: dict[str, Any] | None,
        hit_lookup: dict[str, KolHit],
        now_dt,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        per_author_counts: dict[str, int] = defaultdict(int)
        ai_items = ai_payload.get("worth_reading") if ai_payload else None

        if isinstance(ai_items, list):
            for candidate in ai_items:
                if not isinstance(candidate, dict):
                    continue
                username = self._normalize_username(candidate.get("username"))
                hit = hit_lookup.get(username)
                if not hit:
                    continue
                post = self._pick_informative_post(hit, candidate.get("tweet_id"))
                tweet_url = self._tweet_url(username, post.id)
                if (
                    tweet_url in seen_urls
                    or per_author_counts[username] >= self.MAX_WORTH_READING_PER_AUTHOR
                    or not self._is_informative_post(post, hit)
                ):
                    continue
                items.append(
                    {
                        "display_name": f"@{username}",
                        "tweet_url": tweet_url,
                        "tags": self._normalize_tags(
                            candidate.get("tags"), hit, post, now_dt
                        ),
                    }
                )
                seen_urls.add(tweet_url)
                per_author_counts[username] += 1
                if len(items) >= self.MAX_WORTH_READING_ITEMS:
                    break

        if items:
            return items

        candidates: list[tuple[KolHit, TweetRecord]] = []
        for hit in hit_lookup.values():
            for post in hit.posts:
                if self._is_informative_post(post, hit):
                    candidates.append((hit, post))
        if not candidates:
            for hit in hit_lookup.values():
                for post in hit.posts[:2]:
                    candidates.append((hit, post))
        candidates.sort(
            key=lambda item: self._post_signal_score(item[1], item[0]),
            reverse=True,
        )
        for hit, post in candidates:
            tweet_url = self._tweet_url(hit.username, post.id)
            if (
                tweet_url in seen_urls
                or per_author_counts[hit.username] >= self.MAX_WORTH_READING_PER_AUTHOR
            ):
                continue
            items.append(
                {
                    "display_name": f"@{hit.username}",
                    "tweet_url": tweet_url,
                    "tags": self._infer_tags(hit, post, now_dt),
                }
            )
            seen_urls.add(tweet_url)
            per_author_counts[hit.username] += 1
            if len(items) >= self.MAX_WORTH_READING_ITEMS:
                break
        return items

    def _build_focus_accounts(
        self,
        ai_payload: dict[str, Any] | None,
        hit_lookup: dict[str, KolHit],
        worth_reading: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        focus_accounts: list[dict[str, str]] = []
        seen: set[str] = set()
        ai_items = ai_payload.get("focus_accounts") if ai_payload else None
        if isinstance(ai_items, list):
            for item in ai_items:
                if not isinstance(item, dict):
                    continue
                username = self._normalize_username(item.get("username"))
                if not username or username in seen or username not in hit_lookup:
                    continue
                focus_accounts.append(
                    {
                        "username": username,
                        "reason": self._safe_text(
                            item.get("reason"),
                            "今天的信息密度和后续跟踪价值都相对更高。",
                        ),
                    }
                )
                seen.add(username)
                if len(focus_accounts) >= 5:
                    return focus_accounts

        for item in worth_reading[:5]:
            username = self._normalize_username(item["display_name"])
            if not username or username in seen:
                continue
            hit = hit_lookup.get(username)
            if not hit:
                continue
            focus_accounts.append(
                {
                    "username": username,
                    "reason": f"覆盖 `{hit.category}` 相关线索，且 24h 内表达更具代表性。",
                }
            )
            seen.add(username)
        return focus_accounts

    @staticmethod
    def _report_system_prompt() -> str:
        return (
            "你是机构级加密研究助理，需要把过去 24 小时 KOL 推文整理成中文成稿。"
            "请只基于输入数据输出 JSON，不要捏造未提供的信息。"
            "必须包含字段：one_liner, three_points, overview, groups, consensus, differences, focus_accounts, worth_reading。"
            "groups 为数组，每项包含 group_name, group_summary, authors；authors 每项包含 username, tweet_id, core, judgement, watch_reason, tags。"
            "worth_reading 每项包含 username, tweet_id, tags。"
            "要求："
            "1. three_points 为 3 条。"
            "2. overview / consensus / differences 各 2-4 条。"
            "3. 每个 group 只保留最有信息密度的账号，不必覆盖全部命中账号。"
            "4. worth_reading 优先覆盖全部高信息量帖子，不要机械限制在 8 条；通常输出 6-15 条，并且 tweet_id 必须来自输入数据。"
            "5. tags 使用 #KOL/#Topic/#Asset/#Type/#Date 体系。"
            "6. 明确排除 reply/repost/纯闲聊/表情包/体育或生活类跑题内容，优先选择原生观点表达、框架帖、机制分析、政策解读、产品进展。"
        )

    def _report_user_prompt(
        self,
        *,
        title: str,
        start_dt,
        end_dt,
        total_accounts: int,
        fetched_accounts: int,
        hits: list[KolHit],
    ) -> str:
        payload = {
            "title": title,
            "window_start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "window_end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": self.settings.timezone,
            "total_accounts": total_accounts,
            "fetched_accounts": fetched_accounts,
            "hit_count": len(hits),
            "post_count": sum(len(hit.posts) for hit in hits),
            "hits": [
                {
                    "group_name": hit.group_name,
                    "username": hit.username,
                    "role": hit.role,
                    "category": hit.category,
                    "post_count": len(hit.posts),
                    "total_engagement": sum(
                        self._post_engagement(post) for post in hit.posts
                    ),
                    "posts": [
                        {
                            "id": post.id,
                            "created_at": post.created_at.isoformat(),
                            "engagement": self._post_engagement(post),
                            "text": self._summarize_text(post.text, 320),
                        }
                        for post in self._select_posts_for_report(hit)
                    ],
                }
                for hit in hits
            ],
        }
        return "请基于这些真实推文材料生成日报 JSON：\n" + json.dumps(
            payload, ensure_ascii=False, indent=2
        )

    def _render_hit_block(
        self,
        *,
        hit: KolHit,
        post: TweetRecord,
        now_dt,
        core: str,
        judgement: str,
        watch_reason: str,
        tags: list[str],
    ) -> dict[str, Any]:
        return {
            "group_name": hit.group_name,
            "username": hit.username,
            "role": hit.role,
            "core": core,
            "judgement": judgement,
            "watch_reason": watch_reason,
            "tweet_url": self._tweet_url(hit.username, post.id),
            "tags": tags,
            "post_count": len(hit.posts),
            "engagement_label": self._engagement_label(hit.posts),
        }

    @staticmethod
    def _group_hits(hits: list[KolHit]) -> dict[str, list[KolHit]]:
        grouped: dict[str, list[KolHit]] = defaultdict(list)
        for hit in hits:
            grouped[hit.group_name].append(hit)
        return dict(grouped)

    def _fallback_group_summary(self, group_name: str, hits: list[KolHit]) -> str:
        topics = self._topics_overview(hits)
        return f"这一组今天更集中在 {topics}，整体更适合把它们当成分化行情下的线索源。"

    def _fallback_three_points(self, hits: list[KolHit]) -> list[str]:
        if not hits:
            return ["过去 24 小时没有抓到可用帖子，建议优先排查抓取链路和配置项。"]
        return [
            f"命中账号主要集中在 {self._topics_overview(hits)}，说明市场仍以结构性主题为主。",
            "高信号账号更常见的表达是“先看结构、再看催化”，而不是单条推文直接给终局判断。",
            "值得重点跟踪的是连续表达、互动放大和是否出现跨账号共振，而不是只看单次喊单。",
        ]

    def _fallback_consensus(self, hits: list[KolHit]) -> list[str]:
        if not hits:
            return []
        return [
            f"大部分高信号表达都围绕 {self._topics_overview(hits)} 展开，而不是全面 risk-on 或全面 risk-off。",
            "相比空泛口号，KOL 更愿意讨论结构位置、制度窗口和产品化进展。",
        ]

    def _fallback_differences(self, hits: list[KolHit]) -> list[str]:
        if not hits:
            return []
        return [
            "分歧主要在时间尺度上：有人讨论短线执行，有人讨论中长期叙事承接。",
            "同一资产的看法也常分成两类：一类强调价格结构，一类强调监管、产品或 adoption 变量。",
        ]

    def _infer_tags(self, hit: KolHit, post: TweetRecord, now_dt) -> list[str]:
        tags = [f"#KOL/{hit.username}"]
        topics, assets, type_tags = self._detect_tags(hit, post)
        tags.extend(f"#Topic/{item}" for item in topics[:2])
        tags.extend(f"#Asset/{item}" for item in assets[:2])
        tags.extend(f"#Type/{item}" for item in type_tags[:2])
        tags.append(f"#Date/{report_date_str(now_dt)}")
        return tags

    def _normalize_tags(
        self,
        raw_tags: Any,
        hit: KolHit,
        post: TweetRecord,
        now_dt,
    ) -> list[str]:
        if not isinstance(raw_tags, list):
            return self._infer_tags(hit, post, now_dt)
        normalized = []
        for item in raw_tags:
            text = self._safe_text(item)
            if not text:
                continue
            if not text.startswith("#"):
                text = "#" + text
            normalized.append(text)
        if not any(tag.startswith("#KOL/") for tag in normalized):
            normalized.insert(0, f"#KOL/{hit.username}")
        if not any(tag.startswith("#Date/") for tag in normalized):
            normalized.append(f"#Date/{report_date_str(now_dt)}")
        return normalized

    def _detect_tags(
        self, hit: KolHit, post: TweetRecord
    ) -> tuple[list[str], list[str], list[str]]:
        text = f"{hit.category} {post.text}".lower()
        topic_rules = [
            ("BTC", ["bitcoin", "btc"]),
            ("ETH", ["ethereum", "eth"]),
            ("Macro", ["macro", "fed", "nonfarm", "cpi", "inflation", "rates"]),
            ("ETF", ["etf", "sec"]),
            ("Stablecoin", ["stablecoin", "usdc", "usdt", "ousd"]),
            ("Yield", ["yield", "apy", "earn", "savings", "morpho", "spark"]),
            ("Adoption", ["adoption", "philippines", "treasury", "institution"]),
            (
                "Altcoins",
                ["altcoin", "alts", "solana", "ondo", "near", "tao", "eigen", "jup"],
            ),
            ("HYPE", ["hype"]),
        ]
        type_rules = [
            ("TA", ["structure", "support", "resistance", "breakdown", "uptrend"]),
            ("Framework", ["framework", "cycle", "thesis"]),
            ("PolicyReadout", ["sec", "regulation", "policy", "approval"]),
            ("Productization", ["yield", "earn", "morpho", "spark", "app"]),
            ("Expansion", ["expansion", "philippines", "launch"]),
        ]
        asset_rules = [
            ("BTC", ["bitcoin", "btc"]),
            ("ETH", ["ethereum", "eth"]),
            ("SOL", ["solana", "$w"]),
            ("NEAR", ["near"]),
            ("TAO", ["tao"]),
            ("ONDO", ["ondo"]),
            ("HYPE", ["hype"]),
        ]
        return (
            self._match_rules(text, topic_rules, default=["Market"]),
            self._match_rules(text, asset_rules),
            self._match_rules(text, type_rules, default=["Framework"]),
        )

    @staticmethod
    def _match_rules(
        text: str, rules: list[tuple[str, list[str]]], default: list[str] | None = None
    ) -> list[str]:
        results = []
        for label, keywords in rules:
            if any(keyword in text for keyword in keywords):
                results.append(label)
        if results:
            return results
        return default or []

    @staticmethod
    def _tweet_url(username: str, tweet_id: str) -> str:
        return f"https://x.com/{username}/status/{tweet_id}"

    @staticmethod
    def _normalize_username(value: Any) -> str:
        text = str(value or "").strip()
        if text.startswith("@"):
            text = text[1:]
        return text

    @staticmethod
    def _post_engagement(post: TweetRecord) -> int:
        return (
            post.like_count + post.retweet_count + post.reply_count + post.quote_count
        )

    def _post_signal_score(self, post: TweetRecord, hit: KolHit) -> int:
        return (
            self._post_engagement(post)
            + min(len(post.text or ""), 300)
            + len(hit.posts) * 30
        )

    def _is_informative_post(self, post: TweetRecord, hit: KolHit) -> bool:
        text = re.sub(r"\s+", " ", post.text or "").strip()
        if len(text) < 40:
            return False
        if self._looks_like_reply_or_repost(text):
            return False
        if self._looks_like_low_signal_smalltalk(text):
            return False

        score = self._post_signal_score(post, hit)
        if score >= self.MIN_INFORMATIVE_POST_SCORE:
            return True

        lowered = text.lower()
        signal_keywords = [
            "etf",
            "sec",
            "fed",
            "nonfarm",
            "inflation",
            "rates",
            "treasury",
            "stablecoin",
            "yield",
            "morpho",
            "spark",
            "bitcoin",
            "ethereum",
            "solana",
            "ondo",
            "near",
            "tao",
            "framework",
            "cycle",
            "adoption",
        ]
        return any(keyword in lowered for keyword in signal_keywords)

    @staticmethod
    def _looks_like_reply_or_repost(text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith("rt @"):
            return True
        if lowered.startswith("@"):
            return True
        if lowered.startswith("repost @") or lowered.startswith("reposted @"):
            return True
        if text.count("@") >= 2 and len(text) < 180:
            return True
        return False

    @staticmethod
    def _looks_like_low_signal_smalltalk(text: str) -> bool:
        lowered = text.lower()
        smalltalk_patterns = [
            "gm",
            "gn",
            "haha",
            "lol",
            "lmao",
            "that’s fair",
            "that's fair",
            "wild haha",
            "so shaky",
            "buff",
            "拥抱吗",
            "还在跌",
        ]
        crypto_keywords = [
            "btc",
            "bitcoin",
            "eth",
            "ethereum",
            "etf",
            "sec",
            "stablecoin",
            "yield",
            "macro",
            "nonfarm",
            "rates",
            "inflation",
            "solana",
            "ondo",
            "near",
            "tao",
            "eigen",
            "morpho",
            "spark",
            "treasury",
            "rwa",
            "ai",
        ]
        if any(keyword in lowered for keyword in crypto_keywords):
            return False
        return any(pattern in lowered for pattern in smalltalk_patterns)

    def _hit_signal_score(self, hit: KolHit) -> int:
        return (
            sum(self._post_engagement(post) for post in hit.posts)
            + len(hit.posts) * 100
        )

    def _pick_post(self, hit: KolHit, tweet_id: Any) -> TweetRecord:
        tweet_id_str = str(tweet_id or "").strip()
        for post in hit.posts:
            if post.id == tweet_id_str:
                return post
        return max(hit.posts, key=lambda item: self._post_signal_score(item, hit))

    def _pick_informative_post(self, hit: KolHit, tweet_id: Any) -> TweetRecord:
        tweet_id_str = str(tweet_id or "").strip()
        informative_posts = self._select_posts_for_report(hit)
        for post in informative_posts:
            if post.id == tweet_id_str:
                return post
        for post in hit.posts:
            if post.id == tweet_id_str and self._is_informative_post(post, hit):
                return post
        if informative_posts:
            return informative_posts[0]
        return self._pick_post(hit, tweet_id)

    def _select_posts_for_report(self, hit: KolHit) -> list[TweetRecord]:
        informative_posts = [
            post for post in hit.posts if self._is_informative_post(post, hit)
        ]
        if not informative_posts:
            return sorted(
                hit.posts,
                key=lambda item: self._post_signal_score(item, hit),
                reverse=True,
            )[: self.MIN_REPORT_POSTS_PER_AUTHOR]
        return sorted(
            informative_posts,
            key=lambda item: self._post_signal_score(item, hit),
            reverse=True,
        )[: self.MIN_REPORT_POSTS_PER_AUTHOR]

    def _engagement_label(self, posts: list[TweetRecord]) -> str:
        total = sum(self._post_engagement(post) for post in posts)
        if total >= 3000:
            return "高"
        if total >= 500:
            return "中"
        return "低"

    def _topics_overview(self, hits: list[KolHit]) -> str:
        topic_scores: dict[str, int] = defaultdict(int)
        for hit in hits:
            topics, _, _ = self._detect_tags(hit, hit.posts[0])
            for topic in topics:
                topic_scores[topic] += 1
        if not topic_scores:
            return "`市场结构`、`制度窗口`、`产品化线索`"
        top_topics = sorted(topic_scores.items(), key=lambda item: (-item[1], item[0]))[
            :4
        ]
        return "、".join(f"`{name}`" for name, _ in top_topics)

    @staticmethod
    def _summarize_text(text: str | None, limit: int = 120) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return "当前未拿到可用原文。"
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1] + "…"

    @staticmethod
    def _safe_text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    def _safe_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [self._safe_text(item) for item in value if self._safe_text(item)]

    def _archive_base_records(self, payload: dict[str, Any]) -> tuple[list[str], str]:
        blocker = self.publisher.get_base_archive_blocker()
        if blocker:
            note = f"未执行（{blocker}）"
            log_event(
                self.logger,
                job="kol_report",
                stage="feishu_base_archive",
                status="skipped",
                detail=blocker,
            )
            return [], note

        try:
            record_ids = self.publisher.batch_create_base_records(payload)
        except Exception as exc:
            note = f"失败（{exc}）"
            log_event(
                self.logger,
                job="kol_report",
                stage="feishu_base_archive",
                status="warning",
                detail=str(exc),
            )
            return [], note

        return record_ids, ""

    def _build_summary_markdown(
        self,
        title: str,
        hit_count: int,
        post_count: int,
        record_count: int,
        base_note: str = "",
        doc_url: str = "",
        doc_note: str = "",
        one_liner: str = "",
        worth_reading_count: int = 0,
    ) -> str:
        lines = [
            "今日加密 KOL 过去 24 小时监控报告已更新：",
            "",
            f"- 标题：{title}",
            f"- 命中账号：{hit_count}",
            f"- 有效帖子：{post_count}",
            f"- 值得一读：{worth_reading_count} 条",
        ]
        if one_liner:
            lines.append(f"- 今日一句话：{one_liner}")
        if base_note:
            lines.append(f"- Base 归档：{base_note}")
        else:
            lines.append(f"- Base 归档：{record_count} 条")
        if doc_url:
            lines.append(f"- 云文档：{doc_url}")
        elif doc_note:
            lines.append(f"- 云文档：{doc_note}")
        return "\n".join(lines)
