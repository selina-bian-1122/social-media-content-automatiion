"""poll 模式：定时拉取会话消息（im/v1/messages list），无需订阅事件。

- 首次监听某会话时从“当前时间”开始，不回放历史消息
- 游标与已处理 message_id 持久化在 state/bot_state.json，重启不会重复执行
- 只处理 sender_type == "user" 的消息，bot 自己发的消息会被跳过
"""

import logging
import time

import lark_oapi as lark
from lark_oapi.api.im.v1 import ListMessageRequest

import config
import lark_client
from bot import commands, state

logger = logging.getLogger(__name__)


def _fetch_since(chat_id: str, start_ms: int) -> list:
    items, page_token = [], None
    while True:
        req = ListMessageRequest.builder() \
            .container_id_type("chat") \
            .container_id(chat_id) \
            .start_time(str(start_ms // 1000)) \
            .sort_type("ByCreateTimeAsc") \
            .page_size(50)
        if page_token:
            req = req.page_token(page_token)

        resp = lark_client._get_client().im.v1.message.list(req.build())
        if not resp.success():
            raise RuntimeError(f"Lark API error: {resp.code} {resp.msg}")

        items.extend(resp.data.items or [])
        if not resp.data.has_more:
            return items
        page_token = resp.data.page_token


def _poll_chat(chat_id: str) -> None:
    cursor = state.get_cursor(chat_id)
    if cursor is None:
        state.init_cursor(chat_id, int(time.time() * 1000))
        logger.info("开始监听会话 %s（从现在起的新消息）", chat_id)
        return

    seen = set(cursor["seen"])
    for msg in _fetch_since(chat_id, cursor["ts_ms"]):
        create_ms = int(msg.create_time)
        if msg.message_id in seen or create_ms < cursor["ts_ms"] or msg.deleted:
            continue
        # 先标记再处理：即使处理中途崩溃，也不会在重启后重复执行写表/调用 AI
        state.mark_seen(chat_id, msg.message_id, create_ms)
        if msg.sender is None or msg.sender.sender_type != "user":
            continue
        # @ 了人（群里通常是 @bot）才算“对 bot 说话”：未识别的普通聊天静默忽略，识别到的指令照常执行
        addressed = bool(msg.mentions)
        commands.handle_incoming(chat_id, msg.sender.id, msg.msg_type,
                                 msg.body.content if msg.body else "{}", addressed)


def run() -> None:
    chats = sorted(config.BOT_POLL_CHAT_IDS)
    if not chats:
        raise SystemExit("poll 模式需要 LARK_BOT_CHAT_ID 或 BOT_POLL_CHAT_IDS")

    logger.info("poll 模式启动：监听 %d 个会话，间隔 %ds（Ctrl+C 退出）", len(chats), config.BOT_POLL_INTERVAL)
    while True:
        for chat_id in chats:
            try:
                _poll_chat(chat_id)
            except Exception as e:
                logger.error("拉取会话 %s 失败: %s", chat_id, e)
        time.sleep(config.BOT_POLL_INTERVAL)
