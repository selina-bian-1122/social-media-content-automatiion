"""审批类操作：卡片按钮（ws 模式）和文字指令（poll 模式）共用同一套实现。"""

import config
import lark_client
from bot import cards, jobs, state
# 用户侧错误（编号不对、已处理等）统一用同一个异常类型，消息直接展示给用户
from bot.codes import CodeError as ActionError


def _topic(topic_id: str) -> tuple[str, str]:
    topic = lark_client.get_record(config.TABLE_IDS["topics"], topic_id)
    return cards.plain(topic["fields"].get("标题")), cards.plain(topic["fields"].get("状态"))


def adopt_topic(topic_id: str, account_ids: list[str], chat_id: str) -> str:
    if not account_ids:
        raise ActionError("请至少选择一个发布账号")
    title, status = _topic(topic_id)
    if status != "待筛选":
        raise ActionError(f"「{title}」已是「{status}」，无需重复操作")

    lark_client.update_record(config.TABLE_IDS["topics"], topic_id, {
        "状态": "已采纳",
        "适配账号": account_ids,
    })
    jobs.submit("generate_content", chat_id, topic_ids=[topic_id])
    return f"✅ 已采纳「{title}」，正在为 {len(account_ids)} 个账号生成初稿，完成后通知你。"


def reject_topic(topic_id: str) -> str:
    title, status = _topic(topic_id)
    if status != "待筛选":
        raise ActionError(f"「{title}」已是「{status}」，无需重复操作")
    lark_client.update_record(config.TABLE_IDS["topics"], topic_id, {"状态": "已淘汰"})
    return f"🗑 已淘汰「{title}」"


def approve(code: str, chat_id: str) -> str:
    item, previous = state.close_approval(code, "approved")
    if not item:
        raise ActionError(f"找不到待批准操作 {code.upper()}")
    if previous != "pending":
        raise ActionError(f"{code.upper()} 已处理过（{previous}）")
    op = item["op"]
    jobs.submit(op, chat_id)
    return f"✅ 已批准 {code.upper()}：{jobs.OPERATIONS[op][0]}，正在后台执行，完成后通知你。"


def cancel(code: str) -> str:
    item, previous = state.close_approval(code, "cancelled")
    if not item:
        raise ActionError(f"找不到待批准操作 {code.upper()}")
    if previous != "pending":
        raise ActionError(f"{code.upper()} 已处理过（{previous}）")
    return f"已取消 {code.upper()}：{jobs.OPERATIONS[item['op']][0]}"
