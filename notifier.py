"""把流水线结果推送到飞书：新选题 → 审批卡片，其余 → 文字摘要。"""

import json
import logging
import threading

import config
import lark_client
from bot import cards, codes

logger = logging.getLogger(__name__)

_PUSHED_FILE = config.STATE_DIR / "pushed_topics.json"
_lock = threading.Lock()


def _load_pushed() -> set[str]:
    try:
        return set(json.loads(_PUSHED_FILE.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return set()
    except Exception as e:
        logger.warning("读取已推送选题记录失败，按空处理: %s", e)
        return set()


def _save_pushed(ids: set[str]) -> None:
    config.STATE_DIR.mkdir(exist_ok=True)
    _PUSHED_FILE.write_text(json.dumps(sorted(ids)), encoding="utf-8")


def push_pending_topics(chat_id: str | None = None, limit: int = 10,
                        only_new: bool = True) -> int:
    """推送“待筛选”选题卡片。only_new=True 时跳过已推送过的，返回本次推送数量。"""
    chat_id = chat_id or config.LARK_BOT_CHAT_ID
    if not chat_id or chat_id.startswith("oc_xxx"):
        logger.info("未配置 LARK_BOT_CHAT_ID，跳过选题推送")
        return 0

    with _lock:
        topics = lark_client.list_all_records(
            config.TABLE_IDS["topics"], filter_expr='CurrentValue.[状态] = "待筛选"',
        )
        pushed = _load_pushed()
        if only_new:
            topics = [t for t in topics if t["record_id"] not in pushed]
        if not topics:
            return 0

        accounts = codes.active_accounts()
        sent = 0
        for topic in topics[:limit]:
            try:
                lark_client.send_card(chat_id, cards.topic_card(topic, accounts, codes.topic_code(topic)))
                pushed.add(topic["record_id"])
                sent += 1
            except Exception as e:
                logger.error("推送选题卡片失败 %s: %s", topic["record_id"], e)
        _save_pushed(pushed)

    remaining = len(topics) - sent
    if remaining > 0:
        lark_client.send_text(chat_id, f"还有 {remaining} 个待筛选选题未推送，发送「选题」继续查看。")
    return sent


def notify(text: str, chat_id: str | None = None) -> None:
    chat_id = chat_id or config.LARK_BOT_CHAT_ID
    if not chat_id or chat_id.startswith("oc_xxx"):
        return
    try:
        lark_client.send_text(chat_id, text)
    except Exception as e:
        logger.error("发送通知失败: %s", e)
