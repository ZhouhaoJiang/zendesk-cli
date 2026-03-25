"""工单上下文管理 — Markdown 日志文件的读写"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def _cli_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _context_dir() -> Path:
    d = _cli_root() / "工单记录"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_context_path(ticket_id: int) -> Path:
    return _context_dir() / f"{ticket_id}.md"


def context_exists(ticket_id: int) -> bool:
    return get_context_path(ticket_id).is_file()


def read_context(ticket_id: int) -> Optional[str]:
    p = get_context_path(ticket_id)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")


def get_last_comment_count(ticket_id: int) -> Optional[int]:
    """从上下文文件的基本信息表格中提取上次记录的对话数。"""
    content = read_context(ticket_id)
    if not content:
        return None
    m = re.search(r"\|\s*对话数\s*\|\s*(\d+)", content)
    return int(m.group(1)) if m else None


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def save_context(
    ticket_id: int,
    subject: str,
    version: str,
    customer: str,
    status: str,
    priority: str,
    comment_count: int,
    conclusions: List[str],
    operation: str,
    reply_points: str,
    pending_followup: str = "",
) -> Path:
    """首次写入工单上下文文件，返回文件路径。"""
    now = _now_str()

    conclusions_md = "\n".join(f"- {c}" for c in conclusions) if conclusions else "- (待分析)"

    pending_line = f"\n- **待跟进**: {pending_followup}" if pending_followup else ""

    content = f"""# 工单 #{ticket_id} — {subject}

## 基本信息
| 字段 | 值 |
|------|---|
| 版本 | {version} |
| 客户 | {customer} |
| 状态 | {status} |
| 优先级 | {priority} |
| 最后检查 | {now} |
| 对话数 | {comment_count} |

## 关键结论
{conclusions_md}

## 处理记录

### [{now}] 首次处理
- **对话范围**: #1 ~ #{comment_count}
- **操作**: {operation}
- **回复要点**: {reply_points}{pending_line}
"""
    p = get_context_path(ticket_id)
    p.write_text(content, encoding="utf-8")
    return p


def append_followup(
    ticket_id: int,
    prev_comment_count: int,
    new_comment_count: int,
    new_comments_summary: str,
    findings: str,
    reply_points: str,
    pending_followup: str = "",
) -> Path:
    """追加跟进记录到已有上下文文件，同时更新基本信息中的对话数和最后检查时间。"""
    p = get_context_path(ticket_id)
    content = p.read_text(encoding="utf-8")

    now = _now_str()

    content = re.sub(
        r"(\|\s*最后检查\s*\|\s*)[\d\-: ]+",
        rf"\g<1>{now}",
        content,
    )
    content = re.sub(
        r"(\|\s*对话数\s*\|\s*)\d+",
        rf"\g<1>{new_comment_count}",
        content,
    )

    pending_line = f"\n- **待跟进**: {pending_followup}" if pending_followup else ""

    followup_block = f"""
### [{now}] 跟进
- **新增对话**: #{prev_comment_count + 1} ~ #{new_comment_count}
- **新对话摘要**: {new_comments_summary}
- **新发现**: {findings}
- **回复要点**: {reply_points}{pending_line}
"""
    content = content.rstrip("\n") + "\n" + followup_block
    p.write_text(content, encoding="utf-8")
    return p


def update_conclusion(ticket_id: int, conclusions: List[str]) -> None:
    """更新关键结论部分（完整替换）。"""
    p = get_context_path(ticket_id)
    if not p.is_file():
        return
    content = p.read_text(encoding="utf-8")

    conclusions_md = "\n".join(f"- {c}" for c in conclusions)
    content = re.sub(
        r"(## 关键结论\n)[\s\S]*?(?=\n## )",
        rf"\g<1>{conclusions_md}\n\n",
        content,
    )
    p.write_text(content, encoding="utf-8")


def update_status(ticket_id: int, new_status: str) -> None:
    """更新基本信息中的工单状态。"""
    p = get_context_path(ticket_id)
    if not p.is_file():
        return
    content = p.read_text(encoding="utf-8")
    content = re.sub(
        r"(\|\s*状态\s*\|\s*)\S+",
        rf"\g<1>{new_status}",
        content,
    )
    p.write_text(content, encoding="utf-8")


def list_tracked_tickets() -> List[Dict]:
    """列出所有有记录的工单，返回 [{id, subject, status, last_check, comment_count}]。"""
    results = []
    d = _context_dir()
    for f in sorted(d.glob("*.md")):
        tid_match = re.match(r"(\d+)\.md$", f.name)
        if not tid_match:
            continue
        tid = int(tid_match.group(1))
        content = f.read_text(encoding="utf-8")

        subject_m = re.search(r"^# 工单 #\d+ — (.+)$", content, re.MULTILINE)
        status_m = re.search(r"\|\s*状态\s*\|\s*(\S+)", content)
        check_m = re.search(r"\|\s*最后检查\s*\|\s*([\d\-: ]+)", content)
        count_m = re.search(r"\|\s*对话数\s*\|\s*(\d+)", content)

        results.append({
            "id": tid,
            "subject": subject_m.group(1).strip() if subject_m else "",
            "status": status_m.group(1).strip() if status_m else "",
            "last_check": check_m.group(1).strip() if check_m else "",
            "comment_count": int(count_m.group(1)) if count_m else 0,
        })
    return results
