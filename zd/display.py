"""Rich 终端显示工具 — 美化工单输出"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()
err_console = Console(stderr=True)

# ── 颜色映射 ────────────────────────────────────────

STATUS_COLORS = {
    "new": "bright_blue",
    "open": "green",
    "pending": "yellow",
    "hold": "magenta",
    "solved": "cyan",
    "closed": "dim",
}

PRIORITY_COLORS = {
    "urgent": "bold red",
    "high": "red",
    "normal": "yellow",
    "low": "dim",
}


def _color_status(status: str) -> str:
    color = STATUS_COLORS.get(status, "white")
    return f"[{color}]{status}[/{color}]"


def _color_priority(priority: str) -> str:
    if not priority:
        return "[dim]-[/dim]"
    color = PRIORITY_COLORS.get(priority, "white")
    return f"[{color}]{priority}[/{color}]"


def _format_time(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return iso_str[:16] if iso_str else "-"


def _truncate(text: str, max_len: int = 60) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


# ── 工单列表 ─────────────────────────────────────────


def show_tickets(tickets: list[dict], total: Optional[int] = None, page: int = 1):
    if not tickets:
        console.print("[dim]没有找到工单。[/dim]")
        return

    table = Table(
        title=f"工单列表 (共 {total or len(tickets)} 条，第 {page} 页)",
        show_lines=False,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("ID", style="bold", min_width=6, justify="right", no_wrap=True)
    table.add_column("状态", min_width=7, justify="center", no_wrap=True)
    table.add_column("优先级", min_width=6, justify="center", no_wrap=True)
    table.add_column("标题", ratio=1)
    table.add_column("请求者", min_width=10, no_wrap=True)
    table.add_column("更新时间", min_width=16, no_wrap=True)

    for t in tickets:
        requester_id = t.get("requester_id", "")
        table.add_row(
            str(t.get("id", "")),
            _color_status(t.get("status", "")),
            _color_priority(t.get("priority", "")),
            escape(_truncate(t.get("subject", ""), 55)),
            str(requester_id),
            _format_time(t.get("updated_at")),
        )

    console.print(table)


# ── 工单详情 ─────────────────────────────────────────


def show_ticket_detail(ticket: dict):
    t = ticket
    tid = t.get("id", "?")
    subject = t.get("subject", "(无标题)")
    status = t.get("status", "")
    priority = t.get("priority", "")
    created = _format_time(t.get("created_at"))
    updated = _format_time(t.get("updated_at"))
    requester_id = t.get("requester_id", "")
    assignee_id = t.get("assignee_id", "")
    tags = ", ".join(t.get("tags", [])) or "-"
    description = t.get("description", "")

    header = (
        f"[bold]#{tid}[/bold]  {escape(subject)}\n"
        f"状态: {_color_status(status)}  "
        f"优先级: {_color_priority(priority)}  "
        f"请求者: [cyan]{requester_id}[/cyan]  "
        f"受理人: [cyan]{assignee_id or '-'}[/cyan]\n"
        f"创建: {created}  更新: {updated}\n"
        f"标签: [dim]{escape(tags)}[/dim]"
    )

    console.print(Panel(header, title=f"Ticket #{tid}", border_style="blue"))

    if description:
        console.print()
        console.print(
            Panel(escape(description[:2000]), title="描述", border_style="dim")
        )


# ── 评论/对话 ─────────────────────────────────────────


def show_comments(
    comments: list[dict],
    downloaded_images: Optional[Dict[str, Path]] = None,
):
    if not comments:
        console.print("[dim]暂无对话记录。[/dim]")
        return

    downloaded_images = downloaded_images or {}
    console.print(f"\n[bold]对话记录 ({len(comments)} 条)[/bold]\n")

    for i, c in enumerate(comments, 1):
        author_id = c.get("author_id", "?")
        created = _format_time(c.get("created_at"))
        public = c.get("public", True)
        body = c.get("body", c.get("plain_body", ""))
        attachments = c.get("attachments", [])

        visibility = "[green]公开[/green]" if public else "[red]内部[/red]"
        border = "green" if public else "red"

        content_parts = []
        if body:
            content_parts.append(escape(body[:3000]))
        if attachments:
            content_parts.append("")
            content_parts.append(
                f"[bold yellow]附件 ({len(attachments)}):[/bold yellow]"
            )
            for a in attachments:
                fname = a.get("file_name", "unknown")
                ctype = a.get("content_type", "")
                size = a.get("size", 0)
                size_str = f"{size // 1024}KB" if size >= 1024 else f"{size}B"
                url = a.get("content_url", "")
                icon = "🖼" if ctype.startswith("image/") else "📎"
                local_path = downloaded_images.get(url)
                if local_path:
                    content_parts.append(
                        f"  {icon} [cyan]{escape(fname)}[/cyan] ({size_str}) [green]✓ {escape(str(local_path))}[/green]"
                    )
                else:
                    content_parts.append(
                        f"  {icon} [cyan]{escape(fname)}[/cyan] ({size_str})"
                    )
                    if url:
                        content_parts.append(f"     [dim]{escape(url)}[/dim]")

        title = f"#{i}  作者: {author_id}  {created}  {visibility}"
        display_content = (
            "\n".join(content_parts) if content_parts else "[dim](空)[/dim]"
        )
        console.print(
            Panel(
                display_content,
                title=title,
                border_style=border,
            )
        )


def _conversation_author_label(event: dict) -> str:
    author = event.get("author") or {}
    display_name = author.get("display_name") or "?"
    author_type = author.get("type") or "unknown"
    return f"{display_name} ({author_type})"


def _conversation_body(event: dict) -> str:
    content = event.get("content") or {}
    content_type = content.get("type") or "unknown"

    if content_type == "text":
        return content.get("text", "")
    if content_type == "html":
        return content.get("body", "")
    if content_type == "image":
        alt_text = content.get("alt_text") or "image"
        media_url = content.get("media_url") or ""
        return f"[image] {alt_text}\n{media_url}".strip()
    if content_type == "formResponse":
        return content.get("text_fallback", "")
    if content_type == "form":
        lines = ["[form]"]
        for field in content.get("fields", []):
            label = field.get("label") or field.get("name") or "field"
            value = field.get("text") or field.get("email")
            if value is None:
                selected = field.get("select") or []
                value = ", ".join(
                    item.get("label", "") for item in selected if item.get("label")
                )
            lines.append(f"- {label}: {value or ''}".rstrip())
        return "\n".join(lines)
    return f"[{content_type}]"


def show_conversation_log(
    events: list[dict],
    downloaded_images: Optional[Dict[str, Path]] = None,
):
    if not events:
        console.print("[dim]暂无会话记录。[/dim]")
        return

    downloaded_images = downloaded_images or {}
    console.print(f"\n[bold]会话记录 ({len(events)} 条)[/bold]\n")

    for i, event in enumerate(events, 1):
        created = _format_time(event.get("created_at"))
        event_type = event.get("type", "unknown")
        source = (event.get("source") or {}).get("type", "-")
        author_label = _conversation_author_label(event)
        body = _conversation_body(event)
        attachments = event.get("attachments", [])

        content = event.get("content") or {}
        content_parts = []
        if body:
            if content.get("type") == "image":
                media_url = content.get("media_url", "")
                local_path = downloaded_images.get(media_url)
                if local_path:
                    content_parts.append(
                        f"[image] {escape(content.get('alt_text') or 'image')}"
                        f" [green]✓ {escape(str(local_path))}[/green]"
                    )
                else:
                    content_parts.append(escape(body[:3000]))
            else:
                content_parts.append(escape(body[:3000]))
        if attachments:
            content_parts.append("")
            content_parts.append(
                f"[bold yellow]附件 ({len(attachments)}):[/bold yellow]"
            )
            for a in attachments:
                fname = a.get("file_name") or a.get("alt_text") or "unknown"
                url = a.get("content_url") or a.get("media_url") or ""
                local_path = downloaded_images.get(url)
                if local_path:
                    content_parts.append(
                        f"  🖼 [cyan]{escape(fname)}[/cyan] [green]✓ {escape(str(local_path))}[/green]"
                    )
                else:
                    content_parts.append(f"  [cyan]{escape(fname)}[/cyan]")
                    if url:
                        content_parts.append(f"     [dim]{escape(url)}[/dim]")

        if not content_parts:
            content_parts.append("[dim](空)[/dim]")

        title = f"#{i}  {escape(author_label)}  {created}  [dim]{escape(event_type)} | {escape(source)}[/dim]"
        console.print(Panel("\n".join(content_parts), title=title, border_style="cyan"))


def show_raw_conversation_log(events: list[dict]):
    if not events:
        console.print("[dim]暂无会话记录。[/dim]")
        return

    console.print(f"\n[bold]原始会话记录 ({len(events)} 条)[/bold]\n")

    for i, event in enumerate(events, 1):
        created = _format_time(event.get("created_at"))
        event_type = event.get("type", "unknown")
        source = event.get("source") or {}
        author = event.get("author") or {}
        content = event.get("content") or {}
        metadata = event.get("metadata") or {}

        lines = [
            f"type: {event_type}",
            f"created_at: {created}",
            f"author.display_name: {author.get('display_name') or '-'}",
            f"author.type: {author.get('type') or '-'}",
            f"source.type: {source.get('type') or '-'}",
            f"content.type: {content.get('type') or '-'}",
        ]

        if content.get("text"):
            lines.extend(["", content.get("text", "")[:3000]])
        elif content.get("text_fallback"):
            lines.extend(["", content.get("text_fallback", "")[:3000]])
        elif content.get("body"):
            lines.extend(["", content.get("body", "")[:3000]])
        elif content.get("media_url"):
            lines.extend(["", content.get("media_url", "")])

        if metadata:
            lines.extend(
                [
                    "",
                    f"metadata.system keys: {', '.join((metadata.get('system') or {}).keys()) or '-'}",
                    f"metadata.custom keys: {', '.join((metadata.get('custom') or {}).keys()) or '-'}",
                ]
            )

        console.print(
            Panel(
                "\n".join(escape(str(line)) for line in lines),
                title=f"#{i}",
                border_style="magenta",
            )
        )


# ── 搜索结果 ─────────────────────────────────────────


def show_search_results(results: list[dict], total: int = 0):
    if not results:
        console.print("[dim]搜索无结果。[/dim]")
        return
    console.print(f"[bold]搜索到 {total} 条结果:[/bold]\n")
    show_tickets(results, total=total)


# ── 用户信息 ─────────────────────────────────────────


def show_user(user: dict):
    name = str(user.get("name") or "?")
    email = str(user.get("email") or "?")
    role = user.get("role", "?")
    org_id = user.get("organization_id", "-")
    active = "活跃" if user.get("active") else "非活跃"

    info = (
        f"[bold]{escape(name)}[/bold] ({escape(email)})\n"
        f"角色: {role}  组织: {org_id}  状态: {active}"
    )
    console.print(Panel(info, title="用户信息", border_style="cyan"))


# ── 视图列表 ─────────────────────────────────────────


def show_views(views: list[dict]):
    if not views:
        console.print("[dim]没有可用的视图。[/dim]")
        return

    table = Table(title="视图列表")
    table.add_column("ID", style="bold", width=10, justify="right")
    table.add_column("名称", min_width=30)
    table.add_column("活跃", width=6, justify="center")

    for v in views:
        active = "[green]✓[/green]" if v.get("active") else "[red]✗[/red]"
        table.add_row(str(v.get("id", "")), escape(v.get("title", "")), active)

    console.print(table)


# ── 通用 ─────────────────────────────────────────────


def success(msg: str):
    console.print(f"[green]✓[/green] {msg}")


def error(msg: str):
    err_console.print(f"[red]✗ {msg}[/red]")


def warn(msg: str):
    console.print(f"[yellow]⚠ {msg}[/yellow]")


def info(msg: str):
    console.print(f"[blue]ℹ[/blue] {msg}")


# ── 知识库文章 ────────────────────────────────────────


def show_articles(articles: list[dict], total: Optional[int] = None):
    """显示文章搜索结果列表"""
    if not articles:
        console.print("[dim]没有找到文章。[/dim]")
        return

    table = Table(
        title=f"文章列表 (共 {total or len(articles)} 篇)",
        show_lines=False,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("ID", style="bold", min_width=12, justify="right", no_wrap=True)
    table.add_column("标题", ratio=1)
    table.add_column("章节", min_width=10, no_wrap=True)
    table.add_column("更新时间", min_width=16, no_wrap=True)

    for a in articles:
        section_id = a.get("section_id", "-")
        table.add_row(
            str(a.get("id", "")),
            escape(_truncate(a.get("title") or a.get("name", ""), 60)),
            str(section_id),
            _format_time(a.get("updated_at") or a.get("edited_at")),
        )

    console.print(table)


def show_article_detail(article: dict):
    """显示单篇文章详情"""
    title = article.get("title") or article.get("name", "(无标题)")
    article_id = article.get("id", "?")
    html_url = article.get("html_url", "")
    created = _format_time(article.get("created_at"))
    updated = _format_time(article.get("updated_at") or article.get("edited_at"))
    section_id = article.get("section_id", "-")
    label_names = ", ".join(article.get("label_names", [])) or "-"

    header = (
        f"[bold]{escape(str(title))}[/bold]\n"
        f"ID: [cyan]{article_id}[/cyan]  "
        f"章节: [cyan]{section_id}[/cyan]\n"
        f"创建: {created}  更新: {updated}\n"
        f"标签: [dim]{escape(label_names)}[/dim]"
    )
    if html_url:
        header += f"\n链接: [blue underline]{escape(html_url)}[/blue underline]"

    console.print(Panel(header, title=f"Article #{article_id}", border_style="blue"))

    body = article.get("body", "")
    if body:
        # 简单去除 HTML 标签用于终端显示
        import re

        plain = re.sub(r"<[^>]+>", "", body)
        plain = plain.strip()
        if len(plain) > 5000:
            plain = plain[:5000] + "\n\n... (内容过长，已截断)"
        console.print()
        console.print(Panel(plain, title="内容", border_style="dim"))


def show_categories(categories: list[dict]):
    """显示帮助中心分类列表"""
    if not categories:
        console.print("[dim]没有分类。[/dim]")
        return

    table = Table(title="帮助中心分类", show_lines=False, padding=(0, 1), expand=True)
    table.add_column("ID", style="bold", min_width=12, justify="right", no_wrap=True)
    table.add_column("名称", ratio=1)
    table.add_column("描述", ratio=1)

    for c in categories:
        table.add_row(
            str(c.get("id", "")),
            escape(c.get("name", "")),
            escape(_truncate(c.get("description", ""), 50)),
        )

    console.print(table)


def show_sections(sections: list[dict]):
    """显示帮助中心章节列表"""
    if not sections:
        console.print("[dim]没有章节。[/dim]")
        return

    table = Table(title="帮助中心章节", show_lines=False, padding=(0, 1), expand=True)
    table.add_column("ID", style="bold", min_width=12, justify="right", no_wrap=True)
    table.add_column("名称", ratio=1)
    table.add_column("分类 ID", min_width=12, no_wrap=True)
    table.add_column("描述", ratio=1)

    for s in sections:
        table.add_row(
            str(s.get("id", "")),
            escape(s.get("name", "")),
            str(s.get("category_id", "-")),
            escape(_truncate(s.get("description", ""), 50)),
        )

    console.print(table)
