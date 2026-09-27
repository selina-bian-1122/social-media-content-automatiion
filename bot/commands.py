"""收到消息后的统一处理：鉴权 → 文字指令解析（规则匹配，不消耗 AI 调用）。

poll 模式与 ws 模式都走 handle_incoming。
"""

import json
import logging
import re

import config
import lark_client
import notifier
from bot import actions, cards, codes, jobs, state

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"'，。）)]+")
_ADOPT_RE = re.compile(r"^(?:采纳|adopt)\s*(T\d+)\s*(.*)$", re.I)
_REJECT_RE = re.compile(r"^(?:淘汰|reject)\s*(T\d+)\s*$", re.I)
_APPROVE_RE = re.compile(r"^(?:批准|approve|同意)\s*(R\d+)\s*$", re.I)
_CANCEL_RE = re.compile(r"^(?:取消|cancel)\s*(R\d+)\s*$", re.I)

HELP_TEXT = """我能做这些（直接发文字即可）：
· 发链接（可附一句说明）→ 加入素材表，并发起「立即加工」审批
· 「待办」/「状态」→ 各环节待处理数量
· 「选题」→ 推送所有待筛选选题卡片（编号 T#）
· 「采纳 T3 A1 A2」/「采纳 T3 全部」→ 采纳选题并为这些账号生成初稿
· 「淘汰 T3」→ 放弃选题
· 「跑一遍」/「抓取」/「加工」/「生成」→ 发起审批（编号 R#）
· 「批准 R2」/「取消 R2」→ 处理审批
· 「帮助」→ 显示本说明"""

# 关键词 → 需审批的操作；按顺序匹配，先匹配到的生效
_OP_KEYWORDS = [
    (("跑一遍", "全部流程", "完整", "run"), "run_all"),
    (("抓取", "rss"), "fetch_rss"),
    (("加工", "处理素材"), "process_materials"),
    (("生成", "写初稿"), "generate_content"),
]


def is_admin(open_id: str | None) -> bool:
    return bool(open_id) and open_id in config.BOT_ADMIN_OPEN_IDS


def handle_incoming(chat_id: str, open_id: str, msg_type: str, content: str,
                    addressed: bool = True) -> None:
    """处理一条来自用户的消息（已排除 bot 自己发的消息）。

    addressed=False 表示群聊里没有 @ 任何人的普通发言：能识别的指令照常执行，
    识别不了的静默忽略，避免 bot 对日常聊天刷屏。
    """
    if not addressed and msg_type != "text":
        return

    if not config.BOT_ADMIN_OPEN_IDS:
        if not addressed:
            return
        # 绑定模式：尚未配置白名单，只告诉对方 open_id，不执行任何操作
        lark_client.send_text(
            chat_id,
            f"bot 尚未绑定管理员。你的 open_id 是：\n{open_id}\n\n"
            f"请在 .env 的 BOT_ADMIN_EMAILS 填入团队邮箱（或 BOT_ADMIN_OPEN_IDS 填 open_id）后重启 bot_listener.py。",
        )
        return

    if not is_admin(open_id):
        if addressed:
            logger.warning("忽略非白名单用户消息: %s", open_id)
        return

    if msg_type != "text":
        lark_client.send_text(chat_id, "目前只支持文字消息，发送「帮助」查看用法。")
        return

    text = json.loads(content).get("text", "")
    logger.info("收到消息: %s", text[:100])
    try:
        handle_text(chat_id, text, addressed)
    except actions.ActionError as e:
        lark_client.send_text(chat_id, f"⚠️ {e}")
    except Exception as e:
        logger.exception("处理指令失败")
        lark_client.send_text(chat_id, f"❌ 处理失败：{e}")


def handle_text(chat_id: str, text: str, addressed: bool = True) -> None:
    text = re.sub(r"@\S+\s*", "", text).strip()  # 去掉群聊里的 @bot
    lower = text.lower()

    # 审批类指令优先匹配
    if m := _ADOPT_RE.match(text):
        topic_id = codes.resolve_topic(m.group(1))
        lark_client.send_text(chat_id, actions.adopt_topic(topic_id, codes.resolve_accounts(m.group(2)), chat_id))
        return
    if m := _REJECT_RE.match(text):
        lark_client.send_text(chat_id, actions.reject_topic(codes.resolve_topic(m.group(1))))
        return
    if m := _APPROVE_RE.match(text):
        lark_client.send_text(chat_id, actions.approve(m.group(1), chat_id))
        return
    if m := _CANCEL_RE.match(text):
        lark_client.send_text(chat_id, actions.cancel(m.group(1)))
        return

    urls = _URL_RE.findall(text)
    if urls:
        _add_materials(chat_id, urls, _URL_RE.sub("", text).strip())
        return

    if any(k in lower for k in ("帮助", "help", "你能做什么")):
        lark_client.send_text(chat_id, HELP_TEXT)
        return

    if any(k in lower for k in ("待办", "状态", "进度", "todo")):
        lark_client.send_text(chat_id, _status_summary())
        return

    if "选题" in text:
        n = notifier.push_pending_topics(chat_id, only_new=False)
        if n == 0:
            lark_client.send_text(chat_id, "当前没有待筛选的选题。")
        return

    for keywords, op in _OP_KEYWORDS:
        if any(k in lower for k in keywords):
            ask_approval(chat_id, op)
            return

    if addressed:
        lark_client.send_text(chat_id, "没看懂这条指令 🤔\n\n" + HELP_TEXT)


def ask_approval(chat_id: str, op: str, extra: str = "") -> None:
    title, desc = jobs.OPERATIONS[op]
    code = state.new_approval(op, chat_id)
    lark_client.send_card(chat_id, cards.approval_card(title, desc + extra, code))


def _add_materials(chat_id: str, urls: list[str], note: str) -> None:
    description = note or "飞书 bot 提报"
    created = 0
    for url in dict.fromkeys(urls):  # 去重且保序
        try:
            lark_client.create_record(config.TABLE_IDS["materials"], {
                "原文链接": {"link": url, "text": url},
                "素材描述": description,
                "来源": "人工提报",
                "处理状态": "待处理",
            })
            created += 1
        except Exception as e:
            logger.error("写入素材失败 %s: %s", url, e)
            lark_client.send_text(chat_id, f"❌ 写入素材失败：{url}\n{e}")

    if created:
        link = cards.table_link("materials", "素材表")
        ask_approval(chat_id, "process_materials",
                     f"\n\n刚刚已将 **{created}** 条链接写入{link}（待处理）。")


def _count(table_key: str, field: str, value: str) -> int:
    return len(lark_client.list_all_records(
        config.TABLE_IDS[table_key], filter_expr=f'CurrentValue.[{field}] = "{value}"',
    ))


def _status_summary() -> str:
    try:
        return "\n".join([
            "📊 当前待办",
            f"· 素材待处理：{_count('materials', '处理状态', '待处理')}",
            f"· 选题待筛选：{_count('topics', '状态', '待筛选')}",
            f"· 已采纳选题：{_count('topics', '状态', '已采纳')}",
            f"· 初稿待人工编辑：{_count('content', '状态', '待人工编辑')}",
            f"· 初稿待审核：{_count('content', '状态', '待审核')}",
            f"· 已通过待发布：{_count('content', '状态', '已通过')}",
        ])
    except Exception as e:
        logger.exception("统计待办失败")
        return f"❌ 读取表格失败：{e}"
