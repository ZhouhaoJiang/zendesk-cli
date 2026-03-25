"""Zendesk CLI 主入口 — 只读命令"""

import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import click
import requests
from rich.panel import Panel
from rich.table import Table

from .client import ZendeskError, client
from .config import config
from .context import (
    context_exists,
    get_context_path,
    get_last_comment_count,
    list_tracked_tickets,
    read_context,
)
from .display import (
    console,
    error,
    info,
    show_article_detail,
    show_articles,
    show_categories,
    show_comments,
    show_conversation_log,
    show_raw_conversation_log,
    show_search_results,
    show_sections,
    show_ticket_detail,
    show_tickets,
    show_user,
    show_views,
    success,
    warn,
)


def _ensure_config(ctx):
    if not config.validate():
        ctx.exit(1)


def _is_messaging_ticket(ticket: dict) -> bool:
    via = ticket.get("via") or {}
    return (
        bool(ticket.get("from_messaging_channel"))
        or via.get("channel") == "native_messaging"
    )


def _normalize_conversation_events(events: list[dict]) -> list[dict]:
    normalized = []
    for event in events:
        if event.get("type") == "Comment":
            content = event.get("content") or {}
            body = content.get("body", "")
            if body and "Conversation with Web User" in body:
                continue
        normalized.append(event)
    return normalized


def _get_ticket_thread(ticket_id: int, ticket: dict) -> tuple[str, list[dict]]:
    if _is_messaging_ticket(ticket):
        data = client.get_ticket_conversation_log(ticket_id)
        return "conversation_log", _normalize_conversation_events(
            data.get("events", [])
        )
    data = client.get_ticket_comments(ticket_id)
    return "comments", data.get("comments", [])


def _thread_count(ticket_id: int, ticket: dict) -> int:
    _, items = _get_ticket_thread(ticket_id, ticket)
    return len(items)


def _collect_attachment_rows(thread_type: str, items: list[dict]) -> list[dict]:
    rows = []
    for i, item in enumerate(items, 1):
        if thread_type == "comments":
            for attachment in item.get("attachments", []):
                row = dict(attachment)
                row["index"] = i
                row["author"] = str(item.get("author_id", "?"))
                row["file_name"] = row.get("file_name", "unknown")
                row["content_type"] = row.get("content_type", "")
                row["size"] = row.get("size", 0)
                row["url"] = row.get("content_url", "")
                rows.append(row)
            continue

        content = item.get("content") or {}
        if content.get("type") == "image":
            author = (item.get("author") or {}).get("display_name") or "?"
            rows.append(
                {
                    "index": i,
                    "author": author,
                    "file_name": content.get("alt_text") or "image",
                    "content_type": content.get("media_type", "image/*"),
                    "size": content.get("media_size", 0),
                    "url": content.get("media_url", ""),
                }
            )
        for attachment in item.get("attachments", []):
            row = dict(attachment)
            row["index"] = i
            row["author"] = (item.get("author") or {}).get("display_name") or "?"
            row["file_name"] = row.get("file_name") or row.get("alt_text") or "unknown"
            row["content_type"] = row.get("content_type") or row.get("media_type", "")
            row["size"] = row.get("size") or row.get("media_size", 0)
            row["url"] = row.get("content_url") or row.get("media_url", "")
            rows.append(row)
    return rows


_IMG_SRC_RE = re.compile(r'<img\s[^>]*?src=["\']([^"\']+)["\']', re.IGNORECASE)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)")


def _extract_inline_image_urls(body: str) -> list[str]:
    """从 HTML/Markdown body 中提取内联图片 URL，忽略 data: URI。"""
    if not body:
        return []
    urls = []
    for url in _IMG_SRC_RE.findall(body):
        if not url.startswith("data:"):
            urls.append(url)
    for url in _MARKDOWN_IMAGE_RE.findall(body):
        if not url.startswith("data:"):
            urls.append(url)
    return urls


def _collect_all_image_urls(thread_type: str, items: list[dict]) -> list[dict]:
    """收集所有图片 URL：附件中的图片 + HTML body 中的内联图片 + conversation_log image 事件。"""
    images = []
    seen_urls = set()

    for i, item in enumerate(items, 1):
        if thread_type == "comments":
            for att in item.get("attachments", []):
                ctype = att.get("content_type", "")
                url = att.get("content_url", "")
                if ctype.startswith("image/") and url and url not in seen_urls:
                    seen_urls.add(url)
                    images.append(
                        {
                            "index": i,
                            "file_name": att.get("file_name", "image"),
                            "url": url,
                            "source": "attachment",
                        }
                    )
            body = (
                item.get("body")
                or item.get("html_body")
                or item.get("plain_body")
                or ""
            )
            for url in _extract_inline_image_urls(body):
                if url not in seen_urls:
                    seen_urls.add(url)
                    parsed = urlparse(url)
                    query_name = parse_qs(parsed.query).get("name", [""])[0]
                    path_name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
                    fname = query_name or path_name or f"inline_{i}.png"
                    images.append(
                        {
                            "index": i,
                            "file_name": fname,
                            "url": url,
                            "source": "inline",
                        }
                    )
        else:
            content = item.get("content") or {}
            if content.get("type") == "image":
                url = content.get("media_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    images.append(
                        {
                            "index": i,
                            "file_name": content.get("alt_text") or "image",
                            "url": url,
                            "source": "image_event",
                        }
                    )
            for att in item.get("attachments", []):
                ctype = att.get("content_type") or att.get("media_type", "")
                url = att.get("content_url") or att.get("media_url", "")
                if ctype.startswith("image/") and url and url not in seen_urls:
                    seen_urls.add(url)
                    images.append(
                        {
                            "index": i,
                            "file_name": att.get("file_name")
                            or att.get("alt_text")
                            or "image",
                            "url": url,
                            "source": "attachment",
                        }
                    )
    return images


def _manifest_path(out_dir: Path) -> Path:
    return out_dir / ".download-manifest.json"


def _load_download_manifest(out_dir: Path) -> dict[str, str]:
    path = _manifest_path(out_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _save_download_manifest(out_dir: Path, manifest: dict[str, str]) -> None:
    _manifest_path(out_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _next_available_path(out_dir: Path, file_name: str, suffix_index: int) -> Path:
    candidate = out_dir / file_name
    if not candidate.exists():
        return candidate
    return out_dir / f"{candidate.stem}_{suffix_index}{candidate.suffix}"


def _download_ticket_images(
    ticket_id: int, images: list[dict], output_dir: Optional[Path] = None
) -> tuple[dict[str, Path], list[dict], dict[str, Path]]:
    """下载图片到 工单附件/<ticket_id>工单-附件/，返回 (成功映射, 失败列表, 已存在映射)。"""
    if not images:
        return {}, [], {}

    cli_root = Path(__file__).resolve().parent.parent
    out_dir = output_dir or cli_root / "工单附件" / f"{ticket_id}工单-附件"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_download_manifest(out_dir)

    downloaded = {}
    failed = []
    skipped = {}
    for idx, img in enumerate(images, 1):
        fname = img["file_name"]
        url = img["url"]
        if not url:
            continue

        existing_rel = manifest.get(url)
        if existing_rel:
            existing_path = out_dir / existing_rel
            if existing_path.exists():
                skipped[url] = existing_path
                continue

        out_path = _next_available_path(out_dir, fname, idx)

        try:
            resp = requests.get(url, auth=config.auth, timeout=60)
            if resp.ok:
                out_path.write_bytes(resp.content)
                downloaded[url] = out_path
                manifest[url] = out_path.name
                continue

            if "/sc/attachments/" in url:
                try:
                    resp2 = requests.get(url, timeout=60)
                    if resp2.ok:
                        out_path.write_bytes(resp2.content)
                        downloaded[url] = out_path
                        manifest[url] = out_path.name
                        continue
                except Exception:
                    pass
                failed.append({**img, "reason": "sc/attachments 需要浏览器会话认证"})
            else:
                failed.append({**img, "reason": f"HTTP {resp.status_code}"})
        except requests.exceptions.Timeout:
            failed.append({**img, "reason": "下载超时"})
        except Exception as e:
            failed.append({**img, "reason": str(e)[:80]})

    _save_download_manifest(out_dir, manifest)
    return downloaded, failed, skipped


def _export_thread_lines(thread_type: str, items: list[dict]) -> list[str]:
    lines = []
    for i, item in enumerate(items, 1):
        if thread_type == "comments":
            public = "公开" if item.get("public", True) else "内部"
            lines.extend(
                [
                    f"## 对话 #{i} ({public})",
                    f"- **作者 ID**: {item.get('author_id', '')}",
                    f"- **时间**: {item.get('created_at', '')}",
                    "",
                    item.get("body", item.get("plain_body", "")),
                    "",
                    "---",
                    "",
                ]
            )
            continue

        author = item.get("author") or {}
        source = item.get("source") or {}
        content = item.get("content") or {}
        body = ""
        content_type = content.get("type")
        if content_type == "text":
            body = content.get("text", "")
        elif content_type == "html":
            body = content.get("body", "")
        elif content_type == "image":
            body = content.get("media_url", "")
        elif content_type == "formResponse":
            body = content.get("text_fallback", "")
        elif content_type == "form":
            form_lines = ["[form]"]
            for field in content.get("fields", []):
                label = field.get("label") or field.get("name") or "field"
                value = field.get("text") or field.get("email")
                if value is None:
                    selected = field.get("select") or []
                    value = ", ".join(
                        option.get("label", "")
                        for option in selected
                        if option.get("label")
                    )
                form_lines.append(f"- {label}: {value or ''}".rstrip())
            body = "\n".join(form_lines)
        else:
            body = f"[{content_type or 'unknown'}]"

        lines.extend(
            [
                f"## 会话 #{i} ({item.get('type', '')})",
                f"- **作者**: {author.get('display_name', '?')}",
                f"- **作者类型**: {author.get('type', '?')}",
                f"- **来源**: {source.get('type', '')}",
                f"- **时间**: {item.get('created_at', '')}",
                "",
                body,
                "",
                "---",
                "",
            ]
        )
    return lines


# ── 主命令组 ─────────────────────────────────────────


@click.group()
@click.version_option(package_name="zendesk-cli")
@click.option("--debug", is_flag=True, hidden=True, help="显示调试信息")
@click.pass_context
def cli(ctx, debug):
    """zd — Zendesk 命令行工单工具"""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    if debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)


# ── tickets: 列出工单 ────────────────────────────────


@cli.command("tickets")
@click.option(
    "-s",
    "--status",
    type=click.Choice(["new", "open", "pending", "hold", "solved", "closed"]),
    help="按状态筛选",
)
@click.option("-p", "--page", default=1, show_default=True, help="页码")
@click.option("-n", "--per-page", default=25, show_default=True, help="每页条数")
@click.option("--sort", default="updated_at", show_default=True, help="排序字段")
@click.option(
    "--order",
    type=click.Choice(["asc", "desc"]),
    default="desc",
    show_default=True,
    help="排序方向",
)
@click.pass_context
def list_tickets(ctx, status, page, per_page, sort, order):
    """列出工单"""
    _ensure_config(ctx)
    try:
        data = client.list_tickets(
            status=status,
            sort_by=sort,
            sort_order=order,
            page=page,
            per_page=per_page,
        )
        tickets = data.get("tickets") or data.get("results", [])
        total = data.get("count", len(tickets))
        show_tickets(tickets, total=total, page=page)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


# ── ticket: 查看单个工单 ─────────────────────────────


VALID_STATUSES = ("new", "open", "pending", "hold", "solved", "closed")
STATUS_LABELS = {
    "new": "新建",
    "open": "已开启",
    "pending": "待回应",
    "hold": "挂起",
    "solved": "已解决",
    "closed": "已关闭",
}


@cli.command("ticket")
@click.argument("ticket_id", type=int)
@click.option("-c", "--comments", is_flag=True, help="同时显示对话记录")
@click.option("-i", "--with-images", is_flag=True, help="自动下载对话中的图片")
@click.option("--raw-thread", is_flag=True, help="显示更原始的事件类型/来源")
@click.option(
    "--with-context", "with_ctx", is_flag=True, help="同时显示历史上下文和新增对话提示"
)
@click.option("--json-output", "as_json", is_flag=True, help="输出原始 JSON")
@click.option(
    "--set-status",
    "new_status",
    type=click.Choice(VALID_STATUSES),
    default=None,
    help="更新工单状态 (new/open/pending/hold/solved/closed)",
)
@click.pass_context
def view_ticket(ctx, ticket_id, comments, with_images, raw_thread, with_ctx, as_json, new_status):
    """查看工单详情"""
    _ensure_config(ctx)
    try:
        if new_status:
            old_data = client.get_ticket(ticket_id)
            old_status = old_data.get("ticket", {}).get("status", "?")
            if old_status == new_status:
                info(f"工单 #{ticket_id} 状态已经是 {new_status} ({STATUS_LABELS.get(new_status, '')}), 无需更新")
            else:
                client.update_ticket(ticket_id, status=new_status)
                old_label = STATUS_LABELS.get(old_status, old_status)
                new_label = STATUS_LABELS.get(new_status, new_status)
                success(f"工单 #{ticket_id} 状态: {old_status} ({old_label}) → {new_status} ({new_label})")
            if not comments and not as_json:
                return

        data = client.get_ticket(ticket_id)
        ticket = data.get("ticket", data)

        if as_json:
            console.print_json(json.dumps(ticket, ensure_ascii=False))
            return

        if with_ctx and context_exists(ticket_id):
            prev_count = get_last_comment_count(ticket_id) or 0
            ctx_path = get_context_path(ticket_id)
            console.print(
                Panel(
                    f"[bold]已有历史上下文[/bold]: {ctx_path}\n"
                    f"上次记录对话数: {prev_count}",
                    title="📋 工单上下文",
                    border_style="cyan",
                )
            )

        show_ticket_detail(ticket)

        if comments or with_images:
            thread_type, thread_items = _get_ticket_thread(ticket_id, ticket)

            if with_ctx and context_exists(ticket_id):
                prev_count = get_last_comment_count(ticket_id) or 0
                current_count = len(thread_items)
                diff = current_count - prev_count
                if diff > 0:
                    console.print(
                        f"\n[bold yellow]⚡ 新增 {diff} 条对话"
                        f"（从 #{prev_count + 1} 开始）[/bold yellow]\n"
                    )
                elif diff == 0:
                    console.print("\n[dim]对话无变化（与上次记录一致）[/dim]\n")

            downloaded_images = {}
            failed_images = []
            skipped_images = {}
            all_images = []
            if with_images:
                all_images = _collect_all_image_urls(thread_type, thread_items)
                if all_images:
                    console.print(
                        f"\n[bold]正在下载 {len(all_images)} 张图片...[/bold]"
                    )
                    downloaded_images, failed_images, skipped_images = (
                        _download_ticket_images(ticket_id, all_images)
                    )

            if comments or with_images:
                if thread_type == "conversation_log":
                    if raw_thread:
                        show_raw_conversation_log(thread_items)
                    else:
                        show_conversation_log(thread_items, downloaded_images)
                else:
                    show_comments(thread_items, downloaded_images)

            if downloaded_images:
                console.print(
                    f"\n[bold green]✓ 已下载 {len(downloaded_images)} 张图片:[/bold green]"
                )
                for url, path in downloaded_images.items():
                    console.print(f"  📷 [cyan]{path}[/cyan]")
                console.print()

            if skipped_images:
                console.print(
                    f"[bold cyan]↺ 已复用本地图片 {len(skipped_images)} 张[/bold cyan]\n"
                )

            if failed_images:
                console.print(
                    f"\n[bold yellow]⚠ {len(failed_images)} 张图片无法自动下载，请手动在浏览器中打开并发给我:[/bold yellow]"
                )
                for img in failed_images:
                    console.print(
                        f"  ✗ [cyan]{img['file_name']}[/cyan] (对话#{img['index']})"
                    )
                    console.print(f"    [dim]{img['url']}[/dim]")
                console.print()

            if with_images and not all_images:
                info("对话中没有图片。")

    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


# ── reply: 回复工单 ──────────────────────────────────


@cli.command("reply")
@click.argument("ticket_id", type=int)
@click.argument("body", required=False, default=None)
@click.option("--internal", is_flag=True, help="发送内部备注（不对客户可见）")
@click.option(
    "--status",
    type=click.Choice(VALID_STATUSES),
    default=None,
    help="同时更新工单状态",
)
@click.option("-f", "--file", "file_path", type=click.Path(exists=True), help="从文件读取回复内容")
@click.option("-y", "--yes", is_flag=True, help="跳过确认直接发送")
@click.pass_context
def reply_ticket(ctx, ticket_id, body, internal, status, file_path, yes):
    """回复工单（添加公开评论或内部备注）

    \b
    示例:
      zd reply 1709 "We've identified the issue..."
      zd reply 1709 -f reply.txt
      zd reply 1709 "Fixed." --status pending
      zd reply 1709 "Internal note" --internal
    """
    _ensure_config(ctx)

    if file_path:
        body = Path(file_path).read_text(encoding="utf-8").strip()
    elif body is None:
        body = click.edit()
        if not body:
            error("回复内容为空，已取消。")
            return

    body = body.strip()
    if not body:
        error("回复内容为空，已取消。")
        return

    public = not internal
    comment_type = "内部备注" if internal else "公开回复"

    preview_text = body if len(body) <= 100 else body[:100] + "..."
    console.print(f"\n[bold]工单 #{ticket_id} — {comment_type}[/bold]")
    console.print(f"[dim]{preview_text}[/dim]")
    if status:
        console.print(f"同时设置状态 → {status} ({STATUS_LABELS.get(status, '')})")
    console.print()

    if not yes and not click.confirm("确认发送？"):
        info("已取消。")
        return

    try:
        client.reply_ticket(ticket_id, body=body, public=public, status=status)
        success(f"工单 #{ticket_id} {comment_type}已发送 ✓")
        if status:
            success(f"状态已更新 → {status} ({STATUS_LABELS.get(status, '')})")
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


# ── search: 搜索工单 ─────────────────────────────────


@cli.command("search")
@click.argument("query")
@click.option("-p", "--page", default=1, show_default=True, help="页码")
@click.option("-n", "--per-page", default=25, show_default=True, help="每页条数")
@click.option("--sort", default="updated_at", show_default=True, help="排序字段")
@click.option(
    "--order",
    type=click.Choice(["asc", "desc"]),
    default="desc",
    show_default=True,
    help="排序方向",
)
@click.pass_context
def search_tickets(ctx, query, page, per_page, sort, order):
    """搜索工单（支持 Zendesk 搜索语法）

    \b
    示例:
      zd search "dify workflow error"
      zd search "status:open priority:high"
      zd search "created>2024-01-01 tags:billing"
    """
    _ensure_config(ctx)
    try:
        data = client.search_tickets(
            query=query,
            sort_by=sort,
            sort_order=order,
            page=page,
            per_page=per_page,
        )
        results = data.get("results", [])
        total = data.get("count", len(results))
        show_search_results(results, total=total)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


# ── views: 视图 ─────────────────────────────────────


@cli.command("views")
@click.pass_context
def list_views(ctx):
    """列出所有视图"""
    _ensure_config(ctx)
    try:
        data = client.list_views()
        views = data.get("views", [])
        show_views(views)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


@cli.command("view")
@click.argument("view_id", type=int)
@click.option("-p", "--page", default=1, show_default=True, help="页码")
@click.option("-n", "--per-page", default=25, show_default=True, help="每页条数")
@click.pass_context
def view_tickets_by_view(ctx, view_id, page, per_page):
    """查看指定视图中的工单"""
    _ensure_config(ctx)
    try:
        data = client.get_view_tickets(view_id, page=page, per_page=per_page)
        tickets = data.get("tickets", [])
        total = data.get("count", len(tickets))
        show_tickets(tickets, total=total, page=page)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


# ── user: 用户查询 ───────────────────────────────────


@cli.command("me")
@click.pass_context
def current_user(ctx):
    """查看当前认证用户信息"""
    _ensure_config(ctx)
    try:
        data = client.get_current_user()
        user = data.get("user", data)
        show_user(user)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


@cli.command("user")
@click.argument("user_id", type=int)
@click.pass_context
def get_user(ctx, user_id):
    """查看用户信息"""
    _ensure_config(ctx)
    try:
        data = client.get_user(user_id)
        user = data.get("user", data)
        show_user(user)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


# ── export: 导出工单到本地文件 ───────────────────────


@cli.command("export")
@click.argument("ticket_id", type=int)
@click.option("-o", "--output", default=None, help="输出文件路径 (不传则打印到终端)")
@click.pass_context
def export_ticket(ctx, ticket_id, output):
    """导出工单详情和对话为 Markdown"""
    _ensure_config(ctx)
    try:
        tdata = client.get_ticket(ticket_id)
        ticket = tdata.get("ticket", tdata)
        thread_type, thread_items = _get_ticket_thread(ticket_id, ticket)

        lines = [
            f"# Ticket #{ticket_id}: {ticket.get('subject', '')}",
            "",
            f"- **状态**: {ticket.get('status', '')}",
            f"- **优先级**: {ticket.get('priority', '')}",
            f"- **请求者 ID**: {ticket.get('requester_id', '')}",
            f"- **受理人 ID**: {ticket.get('assignee_id', '')}",
            f"- **创建时间**: {ticket.get('created_at', '')}",
            f"- **更新时间**: {ticket.get('updated_at', '')}",
            f"- **标签**: {', '.join(ticket.get('tags', []))}",
            "",
            "---",
            "",
        ]

        lines.extend(_export_thread_lines(thread_type, thread_items))
        markdown = "\n".join(lines)

        if output:
            Path(output).write_text(markdown, encoding="utf-8")
            success(f"工单已导出到: {output}")
        else:
            console.print(markdown)

    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


# ── attachments: 下载工单附件 ────────────────────────


@cli.command("attachments")
@click.argument("ticket_id", type=int)
@click.option(
    "-o", "--output-dir", default=None, help="下载目录 (默认: attachments-<id>/)"
)
@click.option("--list-only", is_flag=True, help="仅列出附件，不下载")
@click.pass_context
def download_attachments(ctx, ticket_id, output_dir, list_only):
    """下载工单中的所有附件"""
    _ensure_config(ctx)
    try:
        tdata = client.get_ticket(ticket_id)
        ticket = tdata.get("ticket", tdata)
        thread_type, thread_items = _get_ticket_thread(ticket_id, ticket)
        all_attachments = _collect_attachment_rows(thread_type, thread_items)
        inline_images = _collect_all_image_urls(thread_type, thread_items)
        attachment_urls = {
            item.get("url") for item in all_attachments if item.get("url")
        }
        inline_images = [
            img for img in inline_images if img.get("url") not in attachment_urls
        ]
        total_items = len(all_attachments) + len(inline_images)

        if not total_items:
            info(f"工单 #{ticket_id} 没有附件或正文图片。")
            return

        console.print(
            f"\n[bold]工单 #{ticket_id} 共有 {total_items} 个附件/正文图片:[/bold]\n"
        )
        for idx, a in enumerate(all_attachments, 1):
            fname = a.get("file_name", "unknown")
            ctype = a.get("content_type", "")
            size = a.get("size", 0)
            size_str = f"{size // 1024}KB" if size >= 1024 else f"{size}B"
            icon = "🖼" if ctype.startswith("image/") else "📎"
            console.print(
                f"  {idx}. {icon} [cyan]{fname}[/cyan]  "
                f"({size_str}, 对话#{a['index']}, 作者:{a['author']})"
            )

        offset = len(all_attachments)
        for idx, img in enumerate(inline_images, 1):
            fname = img.get("file_name", "image")
            console.print(
                f"  {offset + idx}. 🖼 [cyan]{fname}[/cyan]  (正文图片, 对话#{img['index']})"
            )

        if list_only:
            return

        cli_root = Path(__file__).resolve().parent.parent
        default_dir = cli_root / "工单附件" / f"{ticket_id}工单-附件"
        out_dir = Path(output_dir) if output_dir else default_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = _load_download_manifest(out_dir)

        console.print()
        downloaded = 0
        reused = 0
        for idx, a in enumerate(all_attachments, 1):
            fname = a.get("file_name", f"attachment-{idx}")
            url = a.get("url", "")
            if not url:
                error(f"  附件 {fname} 无下载链接，跳过")
                continue

            existing_rel = manifest.get(url)
            if existing_rel:
                existing_path = out_dir / existing_rel
                if existing_path.exists():
                    info(f"{fname} 已存在 → {existing_path}")
                    reused += 1
                    continue

            out_path = _next_available_path(out_dir, fname, idx)

            resp = requests.get(url, auth=config.auth, timeout=60)
            if resp.ok:
                out_path.write_bytes(resp.content)
                manifest[url] = out_path.name
                success(f"{fname} → {out_path}")
                downloaded += 1
            else:
                error(f"{fname} 下载失败 (HTTP {resp.status_code})")
                if resp.status_code == 401 and "/sc/attachments/" in url:
                    warn(
                        "  该附件来自 Messaging `sc/attachments`，当前 API token 无法直接拉取原文件。"
                    )

        _save_download_manifest(out_dir, manifest)

        inline_downloaded, inline_failed, inline_skipped = _download_ticket_images(
            ticket_id, inline_images, out_dir
        )
        for img in inline_images:
            out_path = inline_downloaded.get(img.get("url", ""))
            if out_path:
                success(f"{img.get('file_name', 'image')} → {out_path}")
                downloaded += 1
                continue
            skipped_path = inline_skipped.get(img.get("url", ""))
            if skipped_path:
                info(f"{img.get('file_name', 'image')} 已存在 → {skipped_path}")
                reused += 1
        for img in inline_failed:
            error(
                f"{img.get('file_name', 'image')} 下载失败 ({img.get('reason', 'unknown')})"
            )

        console.print()
        if downloaded:
            success(f"已下载 {downloaded} 个文件到: {out_dir}/")
            if reused:
                info(f"另有 {reused} 个文件已存在，未重复下载。")
        elif reused:
            info(f"没有新增下载，已复用本地 {reused} 个文件: {out_dir}/")
        else:
            warn(f"没有文件成功下载，目标目录: {out_dir}/")

    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


# ── context: 工单上下文管理 ──────────────────────────


@cli.group("context", invoke_without_command=True)
@click.argument("ticket_id", type=int, required=False)
@click.option("--list", "list_all", is_flag=True, help="列出所有有记录的工单")
@click.option("--diff", "show_diff", is_flag=True, help="对比当前对话数 vs 上次记录")
@click.pass_context
def context_cmd(ctx, ticket_id, list_all, show_diff):
    """查看/管理工单上下文记录

    \b
    示例:
      zd context 1640          # 查看工单 1640 的历史上下文
      zd context --list        # 列出所有有记录的工单
      zd context 1640 --diff   # 对比当前 vs 上次的对话数
    """
    if list_all:
        tickets = list_tracked_tickets()
        if not tickets:
            info("暂无工单上下文记录。")
            return

        table = Table(title="工单上下文记录", show_lines=True)
        table.add_column("ID", style="cyan", min_width=6)
        table.add_column("标题", min_width=20, ratio=1)
        table.add_column("状态", min_width=8)
        table.add_column("对话数", min_width=6, justify="center")
        table.add_column("最后检查", min_width=16)

        for t in tickets:
            table.add_row(
                str(t["id"]),
                t["subject"],
                t["status"],
                str(t["comment_count"]),
                t["last_check"],
            )
        console.print(table)
        return

    if not ticket_id:
        console.print("[dim]用法: zd context <ticket_id> 或 zd context --list[/dim]")
        return

    if not context_exists(ticket_id):
        info(f"工单 #{ticket_id} 暂无上下文记录。")
        return

    if show_diff:
        _ensure_config(ctx)
        prev_count = get_last_comment_count(ticket_id) or 0
        try:
            tdata = client.get_ticket(ticket_id)
            ticket = tdata.get("ticket", tdata)
            current_count = _thread_count(ticket_id, ticket)
        except ZendeskError as e:
            error(str(e))
            ctx.exit(1)
            return

        diff = current_count - prev_count
        console.print(f"\n[bold]工单 #{ticket_id} 对话对比:[/bold]")
        console.print(f"  上次记录: {prev_count} 条")
        console.print(f"  当前实际: {current_count} 条")
        if diff > 0:
            console.print(
                f"  [bold yellow]→ 新增 {diff} 条（从 #{prev_count + 1} 开始）[/bold yellow]"
            )
        elif diff == 0:
            console.print("  [dim]→ 无变化[/dim]")
        else:
            warn(f"  → 对话数减少 {abs(diff)} 条（可能有删除）")
        console.print()
        return

    content = read_context(ticket_id) or ""
    ctx_path = get_context_path(ticket_id)
    console.print(
        Panel(
            content,
            title=f"工单 #{ticket_id} 上下文 — {ctx_path}",
            border_style="cyan",
        )
    )


# ── kb: 知识库 (Help Center) ────────────────────────


@cli.group("kb")
def kb_cmd():
    """知识库 (Help Center) 文章查看

    \b
    示例:
      zd kb search "并发调优"
      zd kb article 43503681133204
      zd kb categories
      zd kb sections
      zd kb sections --category 12345
    """
    pass


@kb_cmd.command("search")
@click.argument("query")
@click.option("-p", "--page", default=1, show_default=True, help="页码")
@click.option("-n", "--per-page", default=25, show_default=True, help="每页条数")
@click.option(
    "--locale", default="zh-cn", show_default=True, help="语言 (zh-cn, en-us 等)"
)
@click.pass_context
def kb_search(ctx, query, page, per_page, locale):
    """搜索知识库文章

    \b
    示例:
      zd kb search "并发性能调优"
      zd kb search "plugin daemon"
      zd kb search "部署" --locale en-us
    """
    _ensure_config(ctx)
    try:
        data = client.search_articles(
            query=query, locale=locale, page=page, per_page=per_page
        )
        articles = data.get("results", [])
        total = data.get("count", len(articles))
        show_articles(articles, total=total)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


@kb_cmd.command("article")
@click.argument("article_id", type=int)
@click.option(
    "--locale", default="zh-cn", show_default=True, help="语言 (zh-cn, en-us 等)"
)
@click.option("--url-only", is_flag=True, help="仅输出文章链接")
@click.pass_context
def kb_article(ctx, article_id, locale, url_only):
    """查看单篇文章详情

    \b
    示例:
      zd kb article 43503681133204
      zd kb article 43503681133204 --url-only
    """
    _ensure_config(ctx)
    try:
        data = client.get_article(article_id, locale=locale)
        article = data.get("article", data)
        if url_only:
            url = article.get("html_url", "")
            if url:
                console.print(url)
            else:
                warn("文章没有 html_url 字段")
        else:
            show_article_detail(article)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


@kb_cmd.command("categories")
@click.option(
    "--locale", default="zh-cn", show_default=True, help="语言 (zh-cn, en-us 等)"
)
@click.pass_context
def kb_categories(ctx, locale):
    """列出帮助中心所有分类"""
    _ensure_config(ctx)
    try:
        data = client.list_categories(locale=locale)
        categories = data.get("categories", [])
        show_categories(categories)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


@kb_cmd.command("sections")
@click.option(
    "--category", "category_id", type=int, default=None, help="按分类 ID 筛选"
)
@click.option(
    "--locale", default="zh-cn", show_default=True, help="语言 (zh-cn, en-us 等)"
)
@click.pass_context
def kb_sections(ctx, category_id, locale):
    """列出帮助中心章节

    \b
    示例:
      zd kb sections
      zd kb sections --category 12345
    """
    _ensure_config(ctx)
    try:
        data = client.list_sections(category_id=category_id, locale=locale)
        sections = data.get("sections", [])
        show_sections(sections)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


@kb_cmd.command("list")
@click.argument("section_id", type=int)
@click.option("-p", "--page", default=1, show_default=True, help="页码")
@click.option("-n", "--per-page", default=25, show_default=True, help="每页条数")
@click.option(
    "--locale", default="zh-cn", show_default=True, help="语言 (zh-cn, en-us 等)"
)
@click.pass_context
def kb_list_articles(ctx, section_id, page, per_page, locale):
    """列出某个章节下的所有文章

    \b
    示例:
      zd kb list 12345
    """
    _ensure_config(ctx)
    try:
        data = client.list_articles_in_section(
            section_id=section_id, locale=locale, page=page, per_page=per_page
        )
        articles = data.get("articles", [])
        total = data.get("count", len(articles))
        show_articles(articles, total=total)
    except ZendeskError as e:
        error(str(e))
        ctx.exit(1)


def main():
    cli()


if __name__ == "__main__":
    main()
