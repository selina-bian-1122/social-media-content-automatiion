"""选题/账号短编号：直接使用多维表格里的自动编号字段「编号」。

表格里看到编号 86 的选题就是 T86，账号矩阵编号 2 的账号就是 A2。
自动编号创建后永久不变，与视图排序、筛选、状态变化无关。
"""

import re

import config
import lark_client
from bot import cards

_NUM_FIELD = "编号"
_ALL_WORDS = {"全部", "所有", "all"}


class CodeError(Exception):
    """编号无法解析，消息直接展示给用户。"""


def _num(record: dict) -> str:
    return cards.plain(record["fields"].get(_NUM_FIELD))


def topic_code(record: dict) -> str:
    n = _num(record)
    return f"T{n}" if n else record["record_id"]


def resolve_topic(code: str) -> str:
    m = re.fullmatch(r"[Tt]?(\d+)", code.strip())
    if not m:
        raise CodeError(f"选题编号格式不对：{code}（例如 T86）")
    records = lark_client.list_records(
        config.TABLE_IDS["topics"], filter_expr=f"CurrentValue.[{_NUM_FIELD}] = {int(m.group(1))}",
    )["records"]
    if not records:
        raise CodeError(f"找不到选题 T{m.group(1)}（对应选题库「编号」列）")
    return records[0]["record_id"]


def active_accounts() -> list[tuple[str, str, str]]:
    """启用中的账号：[(A编号, record_id, 显示名)]，按编号排序。"""
    records = lark_client.list_all_records(
        config.TABLE_IDS["accounts"], filter_expr='CurrentValue.[状态] = "启用"',
    )
    result = []
    for r in records:
        f = r["fields"]
        name = cards.plain(f.get("姓名")) or r["record_id"]
        platform = cards.plain(f.get("平台"))
        result.append((f"A{_num(r)}", r["record_id"], f"{name} · {platform}" if platform else name))
    return sorted(result, key=lambda a: int(a[0][1:]) if a[0][1:].isdigit() else 0)


def resolve_accounts(arg: str) -> list[str]:
    """"A1 A2" / "A1,A2" / "全部" → 账号 record_id 列表（只允许启用中的账号）。"""
    accounts = active_accounts()
    tokens = [t for t in re.split(r"[\s,，、]+", arg.strip()) if t]
    if not tokens:
        raise CodeError("请指定账号，例如「采纳 T86 A1 A2」或「采纳 T86 全部」")
    if any(t.lower() in _ALL_WORDS for t in tokens):
        if not accounts:
            raise CodeError("账号矩阵中没有「启用」的账号")
        return [rid for _, rid, _ in accounts]

    by_code = {code: rid for code, rid, _ in accounts}
    ids, unknown = [], []
    for t in tokens:
        rid = by_code.get(t.upper())
        (ids.append(rid) if rid else unknown.append(t))
    if unknown:
        available = "、".join(by_code) or "无"
        raise CodeError(f"未知或未启用的账号编号：{'、'.join(unknown)}（可用：{available}）")
    return list(dict.fromkeys(ids))
