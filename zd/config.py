"""配置管理 — 从 .env 或环境变量读取 Zendesk 认证信息"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 按优先级加载: 项目目录 .env → 用户主目录 ~/.zendesk-cli/.env
_project_env = Path.cwd() / ".env"
_home_env = Path.home() / ".zendesk-cli" / ".env"

if _project_env.exists():
    load_dotenv(_project_env)
elif _home_env.exists():
    load_dotenv(_home_env)


class Config:
    """Zendesk 连接配置"""

    def __init__(self):
        self.subdomain = os.getenv("ZENDESK_SUBDOMAIN", "")
        self.email = os.getenv("ZENDESK_EMAIL", "")
        self.api_token = os.getenv("ZENDESK_API_TOKEN", "")
        self.admin_email = os.getenv("ZENDESK_ADMIN_EMAIL", "")
        self.admin_api_token = os.getenv("ZENDESK_ADMIN_API_TOKEN", "")

    @property
    def has_admin(self) -> bool:
        return bool(self.admin_email and self.admin_api_token)

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}.zendesk.com/api/v2"

    @property
    def auth(self) -> tuple:
        return (f"{self.email}/token", self.api_token)

    @property
    def admin_auth(self) -> tuple:
        """标签等需要更高权限操作使用的 admin 凭据，未配置时回退到普通凭据"""
        if self.has_admin:
            return (f"{self.admin_email}/token", self.admin_api_token)
        return self.auth

    def validate(self) -> bool:
        missing = []
        if not self.subdomain:
            missing.append("ZENDESK_SUBDOMAIN")
        if not self.email:
            missing.append("ZENDESK_EMAIL")
        if not self.api_token:
            missing.append("ZENDESK_API_TOKEN")

        if missing:
            from rich.console import Console
            console = Console(stderr=True)
            console.print(f"[red]缺少配置: {', '.join(missing)}[/red]")
            console.print(
                "请在 .env 文件或环境变量中设置以上配置项。\n"
                "参考 .env.example 模板。"
            )
            return False
        return True


config = Config()
