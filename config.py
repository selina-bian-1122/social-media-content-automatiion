import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# override=True：以 .env 为准，避免被终端/宿主进程里同名的环境变量（如 ANTHROPIC_BASE_URL）静默覆盖
load_dotenv(override=True)

BASE_DIR = Path(__file__).parent

# --- Lark App ---
LARK_APP_ID = os.getenv("LARK_APP_ID", "")
LARK_APP_SECRET = os.getenv("LARK_APP_SECRET", "")
LARK_DOMAIN = os.getenv("LARK_DOMAIN", "https://open.larksuite.com")

# --- Bitable IDs ---
LARK_BASE_APP_TOKEN = os.getenv("LARK_BASE_APP_TOKEN", "")
TABLE_IDS = {
    "materials": os.getenv("LARK_TABLE_MATERIALS", ""),
    "accounts": os.getenv("LARK_TABLE_ACCOUNTS", ""),
    "topics": os.getenv("LARK_TABLE_TOPICS", ""),
    "content": os.getenv("LARK_TABLE_CONTENT", ""),
    "publish": os.getenv("LARK_TABLE_PUBLISH", ""),
    "report": os.getenv("LARK_TABLE_REPORT", ""),
}

# --- Lark Bot ---
# 流水线结果/待审批卡片的推送目标（与 bot 的单聊或群聊 chat_id）
LARK_BOT_CHAT_ID = os.getenv("LARK_BOT_CHAT_ID", "")
def _csv_env(name: str) -> set[str]:
    return {x.strip() for x in os.getenv(name, "").split(",") if x.strip()}


# 允许操作 bot 的用户（白名单）。两种写法可混用，均为逗号分隔：
#   BOT_ADMIN_EMAILS：团队成员飞书邮箱，bot 启动时自动换成 open_id（需 contact:user.id:readonly 权限）
#   BOT_ADMIN_OPEN_IDS：直接填 open_id
# 两者都为空时 bot 处于“绑定模式”，只回显发送者 open_id
BOT_ADMIN_EMAILS = _csv_env("BOT_ADMIN_EMAILS")
BOT_ADMIN_OPEN_IDS = _csv_env("BOT_ADMIN_OPEN_IDS")
# 收消息方式：
#   poll（默认）：定时拉取会话消息，无需在开放平台订阅事件/回调；审批通过文字指令（如「采纳 T3 A1」）
#   ws：长连接接收事件 + 卡片按钮回调，需订阅 im.message.receive_v1 与 card.action.trigger
BOT_MODE = os.getenv("BOT_MODE", "poll").strip().lower()
# poll 模式下要监听的会话 chat_id（逗号分隔），默认监听 LARK_BOT_CHAT_ID
BOT_POLL_CHAT_IDS = _csv_env("BOT_POLL_CHAT_IDS") or ({LARK_BOT_CHAT_ID} if LARK_BOT_CHAT_ID else set())
BOT_POLL_INTERVAL = int(os.getenv("BOT_POLL_INTERVAL", "5"))

# 多维表格网页地址（可选），用于在消息中附带跳转链接，例如 https://xxx.larksuite.com/base/<app_token>
LARK_BASE_URL = os.getenv("LARK_BASE_URL", "").rstrip("/")

# --- 本地状态（已推送的选题等） ---
STATE_DIR = BASE_DIR / "state"

# --- AI ---
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# 使用第三方中转服务时填写服务商提供的接口地址；留空则直连官方
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "") or None
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "") or None

# --- 自动发布（预留，默认关闭）---
# true 时流水线会把【内容库】「已通过」的定稿通过 X API 发布并改为「已发布」（需先实现 automations/publisher.py）
AUTO_PUBLISH = os.getenv("AUTO_PUBLISH", "false").strip().lower() == "true"

# --- Topic domains config ---
_domains_path = BASE_DIR / "config" / "topic_domains.yaml"


def load_domains_config() -> dict:
    with open(_domains_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- Prompt templates ---
_prompts_dir = BASE_DIR / "prompts"


def load_prompt(name: str) -> str:
    path = _prompts_dir / name
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
