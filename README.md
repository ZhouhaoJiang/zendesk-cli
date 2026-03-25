# zd — Zendesk 命令行工单查看工具（只读）

终端里查看 Zendesk 工单：列表、详情、搜索、Markdown 输出，不用切浏览器。
支持 Cursor + Codex 双引擎对比处理工单。

## 快速开始

```bash
# 1. 安装
cd zendesk-cli
uv sync

# 2. 配置
cp .env.example .env
# 编辑 .env 填入 Zendesk 凭据

# 3. 验证（两种方式均可）
uv run zd me          # 直接通过 uv 运行
# 或激活虚拟环境后直接用 zd
source .venv/bin/activate
zd me
```

## 配置说明

| 变量 | 说明 | 获取方式 |
|------|------|----------|
| `ZENDESK_SUBDOMAIN` | 子域名 | URL 中 `xxx.zendesk.com` 的 `xxx` |
| `ZENDESK_EMAIL` | 账号邮箱 | 你的 Zendesk 登录邮箱 |
| `ZENDESK_API_TOKEN` | API Token | Admin → Apps → Zendesk API → Token |

## 命令速查

```bash
# 工单列表
zd tickets                          # 最近更新的工单
zd tickets -s open                  # 只看 open 状态
zd tickets -s pending -p 2          # pending 工单第 2 页

# 查看工单
zd ticket 12345                     # 工单详情
zd ticket 12345 -c                  # 详情 + 对话记录
zd ticket 12345 -c --raw-thread     # Messaging 原始事件类型/来源
zd ticket 12345 --json-output       # 原始 JSON

# 搜索
zd search "workflow error"                # 关键词搜索
zd search "status:open priority:high"     # Zendesk 搜索语法

# 视图
zd views                            # 列出所有视图
zd view 360001234567                # 查看视图中的工单

# 导出
zd export 12345                     # 打印 Markdown 到终端
zd export 12345 -o report.md        # 指定输出文件

# 用户
zd me                               # 当前用户信息
zd user 67890                       # 查看用户信息

# 附件
zd attachments 12345                # 下载附件和正文内联图片到 工单附件/12345工单-附件/
zd attachments 12345 --list-only    # 仅列出不下载
```

## Messaging 工单说明

- `zd ticket <id> -c` 会自动识别 Zendesk Messaging 工单，并优先读取 `conversation_log`
- `zd ticket <id> -c --raw-thread` 可查看更原始的 `event type` / `source.type` / `content.type`
- `zd export <id>` 默认只打印到终端；只有传 `-o` 时才写文件
- `zd attachments <id>` 会同时尝试下载标准附件、正文内联图片和 Messaging 图片，但 `sc/attachments` 这类 URL 可能需要浏览器登录态，API token 不一定能直接下载
- 已下载成功的附件/图片会记录到 `工单附件/<id>工单-附件/.download-manifest.json`，后续重复处理时默认跳过本地已存在文件，只补下载新增内容

## Codex 对比处理

让 Codex (GPT-5.4) 独立处理同一个工单，和 Cursor 的回复交叉验证。

### 方式一：脚本自动（推荐）

```bash
# 在 zendesk-cli 目录下运行
./dual-review.sh 1636

# 自定义 prompt
./dual-review.sh 1636 "帮我回复这个企业版工单，重点看用户截图"
```

脚本会自动：拉工单 → 下载附件 → 把截图传给 Codex → 输出回复到 `codex-reviews/`

### 方式二：手动用 Codex

**重要：必须先在 `saas工单常见问题` 目录下打开 Codex**，这样 Codex 才能读到知识库和源代码。

```bash
# 1. 先切到工作目录
cd ~/Documents/工作/saas工单常见问题

# 2. 启动 Codex
codex

# 3. 在 Codex 里发问题，例如：
#    "帮我处理工单 1636，附件在 zendesk-cli/工单附件/1636工单-附件/ 下"
```

### 输出位置

| 内容 | 路径 |
|------|------|
| Codex 回复 | `codex-reviews/ticket-<id>-codex.md` |
| 工单附件 | `工单附件/<id>工单-附件/` |

## 批量归档

将企业版工单批量归档为本地知识库，用于后续相似工单检索与复用。

```bash
# 归档所有 solved + closed 的企业版工单（跳过已有记录）
python scripts/archive_enterprise_tickets.py

# 归档指定状态
python scripts/archive_enterprise_tickets.py --statuses "new,open,pending"

# 覆盖更新已有记录
python scripts/archive_enterprise_tickets.py --statuses "open,pending" --overwrite

# 限制数量
python scripts/archive_enterprise_tickets.py --limit 50
```

| 内容 | 路径 |
|------|------|
| 工单记录 | `工单记录/<ticket_id>.md` |
| 工单附件 | `工单附件/<ticket_id>工单-附件/` |

## 每日自动更新

已配置 macOS launchd 定时任务，**周一到周五 10:30** 自动执行：

1. **覆盖更新**未解决工单（new, open, pending）的记录和附件
2. **增量归档**新关闭的工单（solved, closed）

```bash
# 查看定时任务状态
launchctl list | grep zendesk

# 手动触发一次
bash scripts/daily_update.sh

# 查看执行日志
ls logs/daily-update-*.log
tail -f logs/daily-update-$(date +%Y%m%d).log

# 卸载定时任务
launchctl unload ~/Library/LaunchAgents/com.zendesk-cli.daily-update.plist

# 重新加载（修改配置后）
launchctl unload ~/Library/LaunchAgents/com.zendesk-cli.daily-update.plist
launchctl load ~/Library/LaunchAgents/com.zendesk-cli.daily-update.plist
```

日志文件自动保留 30 天。
