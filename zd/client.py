"""Zendesk REST API 客户端"""

import logging
from typing import Optional

import requests
from requests.exceptions import ConnectionError, Timeout

from .config import config

logger = logging.getLogger("zd")

DEFAULT_PAGE_SIZE = 25
REQUEST_TIMEOUT = 30


class ZendeskError(Exception):
    """Zendesk API 错误"""

    def __init__(self, status_code: int, message: str, detail: str = ""):
        self.status_code = status_code
        self.message = message
        self.detail = detail
        super().__init__(f"[{status_code}] {message}")


class ZendeskClient:
    """Zendesk API v2 客户端"""

    def __init__(self):
        self.session = requests.Session()
        self.session.auth = config.auth
        self.session.headers.update(
            {
                "Accept": "application/json",
            }
        )
        self.base_url = config.base_url

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except Timeout:
            raise ZendeskError(0, "请求超时", f"URL: {url}")
        except ConnectionError:
            raise ZendeskError(0, "网络连接失败，请检查 ZENDESK_SUBDOMAIN 是否正确")

        if resp.status_code == 401:
            raise ZendeskError(
                401, "认证失败，请检查 ZENDESK_EMAIL 和 ZENDESK_API_TOKEN"
            )
        if resp.status_code == 403:
            raise ZendeskError(403, "权限不足，当前用户无权访问此资源")
        if resp.status_code == 404:
            raise ZendeskError(404, "资源不存在", endpoint)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "60")
            raise ZendeskError(429, f"请求频率超限，请 {retry_after} 秒后重试")

        if not resp.ok:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("error", body.get("description", resp.text[:200]))
            except Exception:
                detail = resp.text[:200]
            raise ZendeskError(resp.status_code, "API 请求失败", str(detail))

        return resp.json()

    def _put(self, endpoint: str, json_data: dict) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            resp = self.session.put(url, json=json_data, timeout=REQUEST_TIMEOUT)
        except Timeout:
            raise ZendeskError(0, "请求超时", f"URL: {url}")
        except ConnectionError:
            raise ZendeskError(0, "网络连接失败，请检查 ZENDESK_SUBDOMAIN 是否正确")

        if resp.status_code == 401:
            raise ZendeskError(401, "认证失败，请检查 ZENDESK_EMAIL 和 ZENDESK_API_TOKEN")
        if resp.status_code == 403:
            raise ZendeskError(403, "权限不足，当前用户无权执行此操作")
        if resp.status_code == 404:
            raise ZendeskError(404, "资源不存在", endpoint)
        if resp.status_code == 422:
            detail = ""
            try:
                body = resp.json()
                detail = str(body.get("error", body.get("details", resp.text[:200])))
            except Exception:
                detail = resp.text[:200]
            raise ZendeskError(422, "参数验证失败", detail)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "60")
            raise ZendeskError(429, f"请求频率超限，请 {retry_after} 秒后重试")

        if not resp.ok:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("error", body.get("description", resp.text[:200]))
            except Exception:
                detail = resp.text[:200]
            raise ZendeskError(resp.status_code, "API 请求失败", str(detail))

        return resp.json()

    # ── 工单 ──────────────────────────────────────────

    def list_tickets(
        self,
        status: Optional[str] = None,
        assignee_id: Optional[int] = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        page: int = 1,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        params = {
            "sort_by": sort_by,
            "sort_order": sort_order,
            "page": page,
            "per_page": per_page,
        }
        if status:
            return self.search_tickets(
                query=f"type:ticket status:{status}",
                sort_by=sort_by,
                sort_order=sort_order,
                page=page,
                per_page=per_page,
            )
        if assignee_id:
            return self._get(f"users/{assignee_id}/tickets/assigned", params=params)
        return self._get("tickets", params=params)

    def get_ticket(self, ticket_id: int) -> dict:
        return self._get(f"tickets/{ticket_id}")

    def update_ticket(self, ticket_id: int, **fields) -> dict:
        return self._put(f"tickets/{ticket_id}", {"ticket": fields})

    def reply_ticket(
        self, ticket_id: int, body: str, public: bool = True, status: Optional[str] = None
    ) -> dict:
        """回复工单（公开评论或内部备注），可同时更新状态"""
        ticket_payload: dict = {
            "comment": {"body": body, "public": public},
        }
        if status:
            ticket_payload["status"] = status
        return self._put(f"tickets/{ticket_id}", {"ticket": ticket_payload})

    def add_internal_note(
        self, ticket_id: int, body: str, status: Optional[str] = None
    ) -> dict:
        """添加内部备注（不对客户可见），可同时更新状态"""
        return self.reply_ticket(ticket_id, body=body, public=False, status=status)

    def get_ticket_comments(
        self, ticket_id: int, page: int = 1, per_page: int = 100
    ) -> dict:
        return self._get(
            f"tickets/{ticket_id}/comments",
            params={"page": page, "per_page": per_page},
        )

    def get_ticket_conversation_log(
        self, ticket_id: int, page_size: int = 100, after: Optional[str] = None
    ) -> dict:
        params: dict[str, object] = {"page[size]": page_size}
        if after:
            params["page[after]"] = after
        return self._get(f"tickets/{ticket_id}/conversation_log", params=params)

    # ── 标签 ─────────────────────────────────────────

    def set_ticket_tags(self, ticket_id: int, tags: list[str]) -> dict:
        """替换工单的全部标签（覆盖写）"""
        return self._put(f"tickets/{ticket_id}", {"ticket": {"tags": tags}})

    def add_ticket_tags(self, ticket_id: int, tags: list[str]) -> dict:
        """增量添加标签，不影响已有标签（使用 additional_tags 原子操作）"""
        return self._put(f"tickets/{ticket_id}", {"ticket": {"additional_tags": tags}})

    def remove_ticket_tags(self, ticket_id: int, tags: list[str]) -> dict:
        """移除指定标签，保留其余标签（使用 remove_tags 原子操作）"""
        return self._put(f"tickets/{ticket_id}", {"ticket": {"remove_tags": tags}})

    def get_ticket_tags(self, ticket_id: int) -> list[str]:
        """获取工单当前所有标签"""
        ticket = self.get_ticket(ticket_id)
        return ticket.get("ticket", {}).get("tags", [])

    # ── 搜索 ─────────────────────────────────────────

    def search_tickets(
        self,
        query: str,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        page: int = 1,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        params = {
            "query": f"type:ticket {query}" if "type:" not in query else query,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "page": page,
            "per_page": per_page,
        }
        return self._get("search", params=params)

    # ── 用户 ─────────────────────────────────────────

    def get_user(self, user_id: int) -> dict:
        return self._get(f"users/{user_id}")

    def get_current_user(self) -> dict:
        return self._get("users/me")

    def search_users(self, query: str) -> dict:
        return self._get("users/search", params={"query": query})

    # ── 视图 ─────────────────────────────────────────

    def list_views(self) -> dict:
        return self._get("views")

    def get_view_tickets(
        self, view_id: int, page: int = 1, per_page: int = DEFAULT_PAGE_SIZE
    ) -> dict:
        return self._get(
            f"views/{view_id}/tickets",
            params={"page": page, "per_page": per_page},
        )

    # ── 组织 ─────────────────────────────────────────

    def get_organization(self, org_id: int) -> dict:
        return self._get(f"organizations/{org_id}")

    # ── 知识库 (Help Center) ─────────────────────────

    def search_articles(
        self,
        query: str,
        locale: str = "zh-cn",
        page: int = 1,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """搜索帮助中心文章"""
        params = {
            "query": query,
            "locale": locale,
            "page": page,
            "per_page": per_page,
        }
        return self._get("help_center/articles/search", params=params)

    def get_article(self, article_id: int, locale: str = "zh-cn") -> dict:
        """获取单篇文章详情"""
        return self._get(f"help_center/{locale}/articles/{article_id}")

    def list_categories(self, locale: str = "zh-cn") -> dict:
        """列出帮助中心所有分类"""
        return self._get(f"help_center/{locale}/categories")

    def list_sections(
        self, category_id: Optional[int] = None, locale: str = "zh-cn"
    ) -> dict:
        """列出帮助中心章节（可按分类筛选）"""
        if category_id:
            return self._get(f"help_center/{locale}/categories/{category_id}/sections")
        return self._get(f"help_center/{locale}/sections")

    def list_articles_in_section(
        self,
        section_id: int,
        locale: str = "zh-cn",
        page: int = 1,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """列出某个章节下的文章"""
        return self._get(
            f"help_center/{locale}/sections/{section_id}/articles",
            params={"page": page, "per_page": per_page},
        )


client = ZendeskClient()
