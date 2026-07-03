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
        report_date = report_date_str(now_dt)
        hit_lookup = {hit.username: hit for hit in hits}
        informative_hit_lookup = {
            hit.username: hit for hit in hits if self._select_posts_for_report(hit)
        }
        informative_hits = list(informative_hit_lookup.values())
        informative_grouped_hits = self._group_hits(informative_hits)
        post_count = sum(
            len(self._select_posts_for_report(hit)) for hit in informative_hits
        )
        ai_payload: dict[str, Any] | None = None

        if informative_hits and self.deepseek.is_configured():
            try:
                ai_payload = self.deepseek.generate_json(
                    system_prompt=self._report_system_prompt(),
                    user_prompt=self._report_user_prompt(
                        title=title,
                        start_dt=start_dt,
                        end_dt=end_dt,
                        total_accounts=total_accounts,
                        fetched_accounts=len(fetched_accounts),
                        hits=informative_hits,
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
            grouped_hits=informative_grouped_hits,
            hit_lookup=informative_hit_lookup,
            now_dt=now_dt,
        )
        worth_reading = self._build_worth_reading(
            ai_payload, informative_hit_lookup, now_dt
        )
        self._align_group_worth_reading_links(groups, worth_reading)
        focus_accounts = self._build_focus_accounts(
            ai_payload, informative_hit_lookup, worth_reading
        )

        low_signal_accounts = sorted(
            username
            for username in hit_lookup
            if username not in informative_hit_lookup
        )
        overview = self._safe_list(ai_payload.get("overview") if ai_payload else None)
        if not overview:
            overview = [
                f"本次配置追踪 `{total_accounts}` 个账号，其中成功拉取 `{len(fetched_accounts)}` 个。",
                f"过去 24 小时命中 `{len(informative_hits)}` 个账号，约 `{post_count}` 条有效帖子。",
                f"高频主题主要集中在：{self._topics_overview(informative_hits)}。",
            ]

        three_points = self._safe_list(
            ai_payload.get("three_points") if ai_payload else None
        )
        if not three_points:
            three_points = self._fallback_three_points(informative_hits)

        consensus = self._safe_list(ai_payload.get("consensus") if ai_payload else None)
        if not consensus:
            consensus = self._fallback_consensus(informative_hits)

        differences = self._safe_list(
            ai_payload.get("differences") if ai_payload else None
        )
        if not differences:
            differences = self._fallback_differences(informative_hits)

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
            "hit_count": len(informative_hits),
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
                            core=self._finalize_core(
                                self._safe_text(candidate.get("core")),
                                hit,
                                post,
                            ),
                            judgement=self._finalize_judgement(
                                self._safe_text(candidate.get("judgement")),
                                hit,
                                post,
                            ),
                            watch_reason=self._finalize_watch_reason(
                                self._safe_text(candidate.get("watch_reason")),
                                hit,
                                post,
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
                    post=self._pick_informative_post(hit, None),
                    now_dt=now_dt,
                    core=self._build_specific_core(
                        hit, self._pick_informative_post(hit, None)
                    ),
                    judgement=self._build_specific_judgement(
                        hit, self._pick_informative_post(hit, None)
                    ),
                    watch_reason=self._build_specific_watch_reason(
                        hit, self._pick_informative_post(hit, None)
                    ),
                    tags=self._infer_tags(
                        hit, self._pick_informative_post(hit, None), now_dt
                    ),
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
                        "reason": self._finalize_focus_reason(
                            self._safe_text(item.get("reason")),
                            hit_lookup[username],
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
                    "reason": self._build_focus_reason(
                        hit,
                        self._pick_informative_post(hit, self._extract_tweet_id(item)),
                    ),
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
            "7. core 必须写出这条帖子的主张或信息增量，不能只复述情绪。"
            "8. judgement 必须给出明确结论，例如偏多/偏空/偏中性、长期/短线、制度增量/产品进展/结构转强，不要写“继续观察”“线索跟踪”“不要下重结论”之类空话。"
            "9. watch_reason 必须指出后续要观察的具体变量，如 ETF 审批节奏、收益产品扩张、价格结构是否延续、资金是否轮动，不要写泛泛的“是否强化观点”。"
            "10. 如果某个账号只有情绪帖或闲聊帖，就不要把它放进 groups 或 worth_reading。"
            "11. 纯协议宣传、品牌口号、泛政治/阴谋论/社会评论、与加密投资主线弱相关的股市闲聊，也不要纳入正文。"
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
        themes = self._theme_labels(hits)
        if len(themes) >= 2:
            return f"这一组今天主要围绕 `{themes[0]}` 和 `{themes[1]}` 展开，整体更偏结构判断、制度增量或产品化线索。"
        if themes:
            return f"这一组今天的主要增量集中在 `{themes[0]}`，更适合当作判断后续交易主线的线索源。"
        topics = self._topics_overview(hits)
        return f"这一组今天最有信息量的内容集中在 {topics}，提供的主要是结构判断、制度进展或产品化线索。"

    def _fallback_three_points(self, hits: list[KolHit]) -> list[str]:
        if not hits:
            return ["过去 24 小时没有抓到可用帖子，建议优先排查抓取链路和配置项。"]
        return [
            f"命中账号主要集中在 {self._topics_overview(hits)}，说明市场仍以结构性主题为主。",
            "高信号账号更常见的是给出明确框架和变量，例如周期、监管窗口、收益机制和资产轮动，而不是泛泛情绪。",
            "真正值得跟踪的是有连续观点输出、能提供机制解释或给出下一步观察变量的账号，而不是单次喊单或短句吐槽。",
        ]

    def _fallback_consensus(self, hits: list[KolHit]) -> list[str]:
        if not hits:
            return []
        lines: list[str] = []
        theme_counts = self._theme_counts(hits)
        if self._theme_total(theme_counts, ["ETH", "BTC", "Altcoins", "HYPE"]) > 0:
            lines.append(
                "大多数高信号观点并不支持“市场已经走坏”的简单结论，更常见的是：`BTC/ETH/山寨` 仍有结构性机会，但要分资产、分阶段看。"
            )
        if (
            self._theme_total(
                theme_counts, ["ETF", "Macro", "Stablecoin", "Yield", "Adoption"]
            )
            > 0
        ):
            lines.append(
                "制度与产品层面的增量比空泛口号更受关注，尤其是 `ETF/监管窗口`、`稳定币收益机制` 和 `链上产品分发`。"
            )
        if any("宏观" in hit.group_name or "华语" in hit.group_name for hit in hits):
            lines.append(
                "华语和宏观交易派普遍强调 `事件日历 + 仓位纪律 + 价格带执行`，而不是直接给单边终局判断。"
            )
        return lines[:3]

    def _fallback_differences(self, hits: list[KolHit]) -> list[str]:
        if not hits:
            return []
        lines: list[str] = []
        theme_counts = self._theme_counts(hits)
        if self._theme_total(theme_counts, ["ETH", "Altcoins", "HYPE"]) > 0:
            lines.append(
                "对 `ETH / 山寨轮动` 的判断分歧最大：一类账号把极端悲观看成反向做多机会，另一类则更强调只有强势资产值得继续跟踪。"
            )
        if self._theme_total(theme_counts, ["Macro", "ETF"]) > 0:
            lines.append(
                "对 `宏观与监管` 的理解也存在差异：有人把它看成风险资产催化，有人更担心审批节奏和通胀路径拖慢兑现速度。"
            )
        lines.append(
            "表达方式上也分成两派：一派偏 `图表结构 / 周期框架`，另一派偏 `制度窗口 / 产品机制`，两者的时间尺度并不一样。"
        )
        return lines[:3]

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
            (
                "Market",
                [
                    "market",
                    "risk-on",
                    "risk off",
                    "liquidity",
                    "rotation",
                    "leverage",
                    "positioning",
                    "volatility",
                ],
            ),
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
            ("TRX", ["tron", "trx"]),
        ]
        return (
            self._match_rules(text, topic_rules),
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
        if self._looks_like_pure_emotion(text):
            return False
        if self._looks_like_offtopic_social_commentary(text):
            return False
        if self._looks_like_generic_brand_marketing(text):
            return False
        if not self._has_core_investment_relevance(text, hit):
            return False

        score = self._post_signal_score(post, hit)
        if score >= self.MIN_INFORMATIVE_POST_SCORE:
            return True

        return self._has_analysis_signal(text)

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

    @staticmethod
    def _looks_like_pure_emotion(text: str) -> bool:
        lowered = text.lower()
        emotion_patterns = [
            "怎么还在跌",
            "继续跌",
            "太难了",
            "难受",
            "无语",
            "服了",
            "崩了",
            "麻了",
            "绝望",
            "气死",
            "笑死",
            "慌",
            "panic",
            "depressed",
            "frustrated",
        ]
        analysis_keywords = [
            "because",
            "therefore",
            "expect",
            "if",
            "then",
            "support",
            "resistance",
            "cycle",
            "framework",
            "approval",
            "inflow",
            "yield",
            "etf",
            "sec",
            "macro",
            "nonfarm",
            "inflation",
            "rates",
            "btc",
            "eth",
            "stablecoin",
            "morpho",
            "spark",
        ]
        if any(keyword in lowered for keyword in analysis_keywords):
            return False
        return any(pattern in lowered for pattern in emotion_patterns)

    @staticmethod
    def _looks_like_offtopic_social_commentary(text: str) -> bool:
        lowered = text.lower()
        off_topic_patterns = [
            "cia",
            "vaccine",
            "paypal mafia",
            "epstein",
            "israel",
            "democracy",
            "monarchy",
            "world cup",
            "soccer",
            "football",
            "marketing号",
            "营销号",
            "政治",
            "阴谋",
            "new feudal",
        ]
        keep_keywords = [
            "btc",
            "bitcoin",
            "eth",
            "ethereum",
            "etf",
            "sec",
            "stablecoin",
            "yield",
            "morpho",
            "spark",
            "tron",
            "defi",
            "onchain",
            "macro",
            "inflation",
            "nonfarm",
            "rates",
        ]
        if any(keyword in lowered for keyword in keep_keywords):
            relevant_hits = sum(keyword in lowered for keyword in keep_keywords)
            off_topic_hits = sum(pattern in lowered for pattern in off_topic_patterns)
            return off_topic_hits >= 2 and relevant_hits <= 1
        return any(pattern in lowered for pattern in off_topic_patterns)

    @staticmethod
    def _looks_like_generic_brand_marketing(text: str) -> bool:
        lowered = text.lower()
        promo_patterns = [
            "interesting direction",
            "built for this kind of scale",
            "built for this scale",
            "more flexible",
            "more global",
            "closer to real time",
            "we are built for",
            "excited to share",
            "proud to announce",
        ]
        substance_keywords = [
            "tvl",
            "revenue",
            "yield",
            "apy",
            "volume",
            "sec",
            "etf",
            "approval",
            "stablecoin",
            "morpho",
            "spark",
            "onchain",
            "defi",
            "treasury",
            "bitcoin",
            "eth",
            "solana",
            "liquidity",
            "adoption",
            "fees",
            "wallet",
            "partnership",
            "settlement",
            "launch",
            "approval",
        ]
        return any(pattern in lowered for pattern in promo_patterns) and not any(
            keyword in lowered for keyword in substance_keywords
        )

    def _has_core_investment_relevance(self, text: str, hit: KolHit) -> bool:
        lowered = text.lower()
        crypto_investment_keywords = [
            "btc",
            "bitcoin",
            "eth",
            "ethereum",
            "etf",
            "sec",
            "stablecoin",
            "yield",
            "morpho",
            "spark",
            "defi",
            "onchain",
            "treasury",
            "solana",
            "tron",
            "trx",
            "ondo",
            "near",
            "tao",
            "eigen",
            "hype",
            "altcoin",
            "alts",
            "token",
            "wallet",
            "protocol",
            "chain",
            "layer 1",
            "rwa",
            "adoption",
            "fees",
            "revenue",
            "liquidity",
        ]
        macro_keywords = [
            "macro",
            "fed",
            "nonfarm",
            "cpi",
            "inflation",
            "rates",
            "rate cut",
            "treasury yield",
            "fomc",
        ]
        market_structure_keywords = [
            "support",
            "resistance",
            "breakout",
            "breakdown",
            "uptrend",
            "downtrend",
            "rotation",
            "positioning",
            "leverage",
            "liquidation",
            "risk-on",
            "risk off",
            "周期",
            "结构",
            "预期",
            "判断",
        ]
        if any(keyword in lowered for keyword in crypto_investment_keywords):
            return True
        if any(keyword in lowered for keyword in macro_keywords):
            return True
        if any(keyword in lowered for keyword in market_structure_keywords):
            has_asset_anchor = any(
                keyword in lowered
                for keyword in [
                    "btc",
                    "bitcoin",
                    "eth",
                    "ethereum",
                    "solana",
                    "tron",
                    "token",
                    "crypto",
                    "加密",
                    "比特币",
                    "以太坊",
                ]
            )
            return has_asset_anchor
        category_lower = (hit.category or "").lower()
        if "宏观" in hit.category and any(
            keyword in lowered for keyword in macro_keywords
        ):
            return True
        return any(
            keyword in category_lower
            for keyword in ["etf", "监管", "稳定币", "defi", "btc", "eth"]
        ) and self._has_analysis_signal(text)

    @staticmethod
    def _has_analysis_signal(text: str) -> bool:
        lowered = text.lower()
        signal_patterns = [
            "because",
            "therefore",
            "which means",
            "this implies",
            "expect",
            "likely",
            "unlikely",
            "bull",
            "bear",
            "support",
            "resistance",
            "breakout",
            "breakdown",
            "inflow",
            "outflow",
            "approval",
            "adoption",
            "yield",
            "pricing",
            "valuation",
            "rotation",
            "周期",
            "预期",
            "判断",
            "意味着",
            "因为",
            "所以",
            "如果",
            "利率",
            "通胀",
            "非农",
            "监管",
            "收益",
            "流动性",
            "结构",
            "杠杆",
            "清算",
            "仓位",
        ]
        return any(pattern in lowered for pattern in signal_patterns)

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

    def _align_group_worth_reading_links(
        self, groups: list[dict[str, Any]], worth_reading: list[dict[str, Any]]
    ) -> None:
        selected_urls = {item["tweet_url"] for item in worth_reading}
        for group in groups:
            for hit in group.get("hits", []):
                if hit.get("tweet_url") not in selected_urls:
                    hit["tweet_url"] = ""

    def _finalize_core(self, candidate: str, hit: KolHit, post: TweetRecord) -> str:
        if candidate and not self._is_vague_statement(candidate):
            return candidate
        return self._build_specific_core(hit, post)

    def _finalize_judgement(
        self, candidate: str, hit: KolHit, post: TweetRecord
    ) -> str:
        if candidate and not self._is_vague_statement(candidate):
            return candidate
        return self._build_specific_judgement(hit, post)

    def _finalize_watch_reason(
        self, candidate: str, hit: KolHit, post: TweetRecord
    ) -> str:
        if candidate and not self._is_vague_statement(candidate):
            return candidate
        return self._build_specific_watch_reason(hit, post)

    def _finalize_focus_reason(self, candidate: str, hit: KolHit) -> str:
        if candidate and not self._is_vague_statement(candidate):
            return candidate
        return self._build_focus_reason(hit, self._pick_informative_post(hit, None))

    def _build_specific_core(self, hit: KolHit, post: TweetRecord) -> str:
        lowered = (post.text or "").lower()
        if any(
            keyword in lowered for keyword in ["not dead", "eth is dead", "eth season"]
        ):
            return "强烈反驳 `ETH 已死` 叙事，认为当前的极端悲观更像阶段性错杀，而不是中期趋势被证伪。"
        if any(
            keyword in lowered
            for keyword in ["hype", "breakdown", "uptrend", "support"]
        ):
            return "继续用 `结构位 / 走势延续` 的框架看盘，认为当前更像趋势中的整理，而不是主升结构已经结束。"
        if any(
            keyword in lowered
            for keyword in ["cycle", "four year", "4 year", "monthly", "bull market"]
        ):
            return "继续把当前波动放回 `大周期 / 四年周期` 框架里解释，强调回撤并不自动等于周期失效。"
        if any(
            keyword in lowered
            for keyword in ["sec", "etf", "approval", "copycat", "innovation"]
        ):
            return "围绕 `SEC 对创新型 ETF` 的态度展开，核心信息是监管并非一味压制，而是在管理审批秩序和新类别放行节奏。"
        if any(
            keyword in lowered
            for keyword in [
                "stablecoin",
                "yield",
                "morpho",
                "spark",
                "ousd",
                "earn",
                "savings",
            ]
        ):
            return "围绕 `稳定币收益机制 / 链上收益产品` 展开，重点不在口号，而在收益分配、流动性和真实用户体验。"
        if any(
            keyword in lowered
            for keyword in ["treasury", "institution", "adoption", "philippines"]
        ):
            return "继续强化 `机构采用 / 平台扩张 / 全球渗透` 叙事，把单条新闻解释成 adoption 持续推进的证据。"
        if any(
            keyword in lowered
            for keyword in ["near", "tao", "ondo", "eigen", "portfolio", "allocation"]
        ):
            return "公开自己的 `组合偏好与轮动方向`，说明资金关注点仍集中在 AI、RWA 和强势山寨资产，而非全面扩散。"
        if any(
            keyword in lowered
            for keyword in ["nonfarm", "inflation", "rates", "fomc", "macro"]
        ):
            return "把 `非农 / 利率 / 通胀 / 风险资产表现` 放进同一交易框架里看，重点是给出事件窗口与价格带之间的映射。"
        text = self._summarize_text(post.text, 160)
        return f"核心信息是：{text}"

    def _build_specific_judgement(self, hit: KolHit, post: TweetRecord) -> str:
        lowered = (post.text or "").lower()
        if any(
            keyword in lowered for keyword in ["not dead", "eth is dead", "eth season"]
        ):
            return "`ETH` 更像被极端悲观情绪错杀，而不是结构性衰退；如果后续相对强弱改善，这类观点对反向布局更有参考价值。"
        if any(
            keyword in lowered
            for keyword in ["hype", "uptrend", "support", "breakdown", "breakout"]
        ):
            return "偏交易结构派的乐观判断，意味着只要关键结构位不破，当前更像健康整理而不是趋势反转。"
        if any(
            keyword in lowered
            for keyword in ["cycle", "four year", "4 year", "bull market"]
        ):
            return "偏 `周期框架延续`，核心意思是当前回撤仍可被视作牛市中的正常波动，而不是大逻辑已经被证伪。"
        if any(
            keyword in lowered
            for keyword in ["sec", "etf", "approval", "regulation", "监管"]
        ):
            return "偏制度增量解读，短线未必立刻兑现，但如果审批边际转松，会先重塑市场对 ETF 和监管路径的预期。"
        if any(
            keyword in lowered
            for keyword in [
                "yield",
                "stablecoin",
                "morpho",
                "spark",
                "product",
                "ousd",
                "收益",
            ]
        ):
            return "偏产品化增量判断，重点不是喊概念，而是这类收益机制若被验证，会同时利多稳定币、借贷协议和分发平台。"
        if any(
            keyword in lowered
            for keyword in ["treasury", "institution", "adoption", "philippines"]
        ):
            return "偏中长期 adoption 视角，说明相关主体在把行业故事从交易竞争推进到真实用户覆盖和资金承接。"
        if any(
            keyword in lowered
            for keyword in ["near", "tao", "ondo", "eigen", "portfolio", "allocation"]
        ):
            return "偏结构轮动思路，不支持全面山寨普涨，但支持强资产继续获得相对收益，弱势标的需要重新筛选。"
        if any(
            keyword in lowered
            for keyword in ["nonfarm", "inflation", "rates", "fomc", "macro"]
        ):
            return "偏事件驱动交易视角，结论不是一味看多或看空，而是强调宏观数据会决定风险资产节奏和仓位管理。"
        return "这条内容提供的是可交易的框架或变量，而不是单纯情绪表达，关键在于后续是否被更多账号和价格走势验证。"

    def _build_specific_watch_reason(self, hit: KolHit, post: TweetRecord) -> str:
        lowered = (post.text or "").lower()
        if any(
            keyword in lowered
            for keyword in ["sec", "etf", "approval", "regulation", "监管"]
        ):
            return "后续重点看监管表态是否继续偏 pro-innovation，以及申请、审批和市场预期是否形成持续催化。"
        if any(
            keyword in lowered
            for keyword in ["yield", "stablecoin", "morpho", "spark", "apy", "收益"]
        ):
            return "后续重点看 TVL、收益可持续性、用户采用和渠道扩张是否同步改善，这决定它是短期营销还是可持续产品线。"
        if any(
            keyword in lowered
            for keyword in [
                "btc",
                "eth",
                "uptrend",
                "breakout",
                "support",
                "resistance",
                "cycle",
                "结构",
            ]
        ):
            return "后续重点看关键结构位是否继续成立、相对强弱是否改善，以及同样的看法是否被更多交易派账号共振。"
        if any(
            keyword in lowered
            for keyword in ["adoption", "treasury", "institution", "philippines"]
        ):
            return "后续重点看 adoption 是否从单点新闻扩散到更多地区、渠道或机构主体，以及是否带来真实流量和资金承接。"
        if any(
            keyword in lowered
            for keyword in ["nonfarm", "inflation", "rates", "fomc", "macro"]
        ):
            return "后续重点看非农、通胀、利率决议和美股风险偏好是否与他给出的交易框架一致。"
        return "后续重点看这条判断能否在价格、资金流向或产品数据上得到验证，而不是只停留在观点层面。"

    def _build_focus_reason(self, hit: KolHit, post: TweetRecord) -> str:
        lowered = (post.text or "").lower()
        if any(
            keyword in lowered
            for keyword in ["near", "tao", "ondo", "eigen", "portfolio", "allocation"]
        ):
            return "兼具组合表达、轮动判断和情绪观察，是今天最完整的交易派样本。"
        if any(
            keyword in lowered for keyword in ["not dead", "eth is dead", "eth season"]
        ):
            return "给出了最明确的 `ETH 反向乐观` 观点，情绪张力和交易指向都很强。"
        if any(
            keyword in lowered
            for keyword in ["nonfarm", "inflation", "rates", "fomc", "macro"]
        ):
            return "把宏观变量、风险资产和关键价格带放进同一框架，属于今天最完整的宏观交易样本。"
        if any(
            keyword in lowered for keyword in ["sec", "etf", "approval", "regulation"]
        ):
            return "提供了对 `SEC/ETF` 制度窗口最直接的增量信息，值得优先跟踪。"
        if any(
            keyword in lowered
            for keyword in ["yield", "stablecoin", "morpho", "spark", "ousd", "收益"]
        ):
            return "代表今天最值得跟踪的 `稳定币 / 链上收益产品化` 线索。"
        if any(
            keyword in lowered
            for keyword in ["cycle", "four year", "4 year", "bull market"]
        ):
            return (
                "给出了最稳定的 `周期框架` 视角，适合用来校验当前波动是否仍在大逻辑内。"
            )
        return f"这位账号围绕 `{hit.category}` 给出了今天最具代表性的增量表达。"

    @staticmethod
    def _extract_tweet_id(item: dict[str, Any]) -> str:
        tweet_url = str(item.get("tweet_url") or "").strip()
        if "/status/" in tweet_url:
            return tweet_url.rsplit("/status/", 1)[-1]
        return ""

    @staticmethod
    def _is_vague_statement(text: str) -> bool:
        lowered = text.lower().strip()
        vague_patterns = [
            "继续观察",
            "线索跟踪",
            "不要下重结论",
            "值得继续跟踪",
            "建议继续观察",
            "更适合把它当作线索",
            "信息密度和后续跟踪价值都相对更高",
            "follow-up",
            "keep watching",
            "wait and see",
            "这条内容更像",
            "定性判断",
            "而不是单纯情绪",
        ]
        return any(pattern in lowered for pattern in vague_patterns)

    def _select_posts_for_report(self, hit: KolHit) -> list[TweetRecord]:
        informative_posts = [
            post for post in hit.posts if self._is_informative_post(post, hit)
        ]
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

    def _theme_counts(self, hits: list[KolHit]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for hit in hits:
            post = self._pick_informative_post(hit, None)
            topics, _, _ = self._detect_tags(hit, post)
            for topic in topics:
                counts[topic] += 1
        return counts

    def _theme_labels(self, hits: list[KolHit]) -> list[str]:
        counts = self._theme_counts(hits)
        return [
            name
            for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
                :3
            ]
        ]

    @staticmethod
    def _theme_total(counts: dict[str, int], labels: list[str]) -> int:
        return sum(counts.get(label, 0) for label in labels)

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
