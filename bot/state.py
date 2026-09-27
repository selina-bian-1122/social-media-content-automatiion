"""bot 本地持久化状态（state/bot_state.json）。

- 待批准操作编号 R1/R2…（选题 T#、账号 A# 直接用表格「编号」列，见 bot/codes.py）
- 轮询游标：每个会话已处理到的时间点和最近处理过的 message_id
"""

import json
import logging
import threading
import time
from typing import Any

import config

logger = logging.getLogger(__name__)

_FILE = config.STATE_DIR / "bot_state.json"
_lock = threading.RLock()
_SEEN_KEEP = 200


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except Exception as e:
        logger.warning("读取 bot 状态失败，按空处理: %s", e)
        data = {}
    data.setdefault("approvals", {})    # "R2" -> {"op", "chat_id", "status", "created"}
    data.setdefault("next_approval", 1)
    data.setdefault("cursors", {})      # chat_id -> {"ts_ms", "seen": [...]}
    return data


def _save(data: dict[str, Any]) -> None:
    config.STATE_DIR.mkdir(exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_FILE)


def _norm(code: str) -> str:
    return code.strip().upper()


# ---------- 待批准操作 ----------

def new_approval(op: str, chat_id: str) -> str:
    with _lock:
        data = _load()
        code = f"R{data['next_approval']}"
        data["approvals"][code] = {
            "op": op, "chat_id": chat_id, "status": "pending", "created": int(time.time()),
        }
        data["next_approval"] += 1
        _save(data)
        return code


def close_approval(code: str, status: str) -> tuple[dict | None, str]:
    """把待批准操作置为 approved/cancelled。返回 (记录, 原状态)；已处理过的不会重复生效。"""
    with _lock:
        data = _load()
        item = data["approvals"].get(_norm(code))
        if not item:
            return None, ""
        previous = item["status"]
        if previous == "pending":
            item["status"] = status
            _save(data)
        return item, previous


# ---------- 轮询游标 ----------

def get_cursor(chat_id: str) -> dict[str, Any] | None:
    return _load()["cursors"].get(chat_id)


def mark_seen(chat_id: str, message_id: str, create_ms: int) -> None:
    with _lock:
        data = _load()
        cur = data["cursors"].setdefault(chat_id, {"ts_ms": 0, "seen": []})
        cur["ts_ms"] = max(cur["ts_ms"], create_ms)
        if message_id not in cur["seen"]:
            cur["seen"] = (cur["seen"] + [message_id])[-_SEEN_KEEP:]
        _save(data)


def init_cursor(chat_id: str, ts_ms: int) -> None:
    with _lock:
        data = _load()
        data["cursors"].setdefault(chat_id, {"ts_ms": ts_ms, "seen": []})
        _save(data)
