"""飞书 bot 常驻进程。启动：python bot_listener.py

两种模式（.env 中 BOT_MODE）：
  · poll（默认）：定时拉取会话消息，无需在开放平台订阅任何事件/回调。
      审批用文字回复：「采纳 T3 A1」「淘汰 T3」「批准 R2」「取消 R2」
      所需权限：im:message:send_as_bot、im:message.p2p_msg:readonly（读单聊）、bitable:app
  · ws：长连接接收事件 + 卡片按钮回调。
      需在「事件与回调」（订阅方式选长连接）订阅 im.message.receive_v1 与 card.action.trigger
两种模式下，用 BOT_ADMIN_EMAILS 配置管理员时都需要 contact:user.id:readonly。
"""

import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import lark_oapi as lark

import config
import lark_client
from bot import actions, cards, commands

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot")


def _resolve_admin_emails() -> None:
    """把 BOT_ADMIN_EMAILS 换成 open_id 并入白名单。"""
    if not config.BOT_ADMIN_EMAILS:
        return
    try:
        mapping = lark_client.get_open_ids_by_emails(sorted(config.BOT_ADMIN_EMAILS))
    except Exception as e:
        logger.error("管理员邮箱解析失败（检查应用是否开通 contact:user.id:readonly）: %s", e)
        return

    for email in sorted(config.BOT_ADMIN_EMAILS):
        open_id = mapping.get(email.lower())
        if open_id:
            config.BOT_ADMIN_OPEN_IDS.add(open_id)
            logger.info("管理员 %s → %s", email, open_id)
        else:
            logger.warning("管理员邮箱未找到对应飞书用户（或不在应用可用范围内）: %s", email)


# ======================= ws 模式（需订阅事件与回调） =======================

# 事件回调需在 3 秒内返回，指令处理放到线程池
_cmd_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cmd")
# 飞书可能重复投递同一事件，按 message_id 去重
_seen: "OrderedDict[str, None]" = OrderedDict()
_seen_lock = threading.Lock()


def _is_duplicate(message_id: str) -> bool:
    with _seen_lock:
        if message_id in _seen:
            return True
        _seen[message_id] = None
        while len(_seen) > 500:
            _seen.popitem(last=False)
        return False


def _on_message(data) -> None:
    msg = data.event.message
    if _is_duplicate(msg.message_id) or msg.chat_type != "p2p":
        return
    _cmd_executor.submit(
        commands.handle_incoming, msg.chat_id, data.event.sender.sender_id.open_id,
        msg.message_type, msg.content,
    )


def _on_card_action(data):
    from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse

    def resp(toast: str, toast_type: str = "info", done: tuple[str, str, str] | None = None):
        body: dict = {"toast": {"type": toast_type, "content": toast}}
        if done:
            body["card"] = {"type": "raw", "data": cards.result_card(*done)}
        return P2CardActionTriggerResponse(body)

    event = data.event
    if not commands.is_admin(event.operator.open_id if event.operator else None):
        return resp("你没有操作权限", "error")

    value = event.action.value or {}
    form = event.action.form_value or {}
    chat_id = event.context.open_chat_id if event.context else config.LARK_BOT_CHAT_ID
    op = value.get("op", "")
    logger.info("卡片操作: %s", value)

    try:
        if op == "adopt_topic":
            msg = actions.adopt_topic(value["topic_id"], form.get("accounts") or [], chat_id)
            return resp("已采纳", "success", ("✅ 选题已采纳", "green", msg))
        if op == "reject_topic":
            msg = actions.reject_topic(value["topic_id"])
            return resp("已淘汰", done=("🗑 选题已淘汰", "grey", msg))
        if op == "approve":
            msg = actions.approve(value["code"], chat_id)
            return resp("已批准", "success", ("✅ 已批准", "green", msg))
        if op == "cancel":
            msg = actions.cancel(value["code"])
            return resp("已取消", done=("已取消", "grey", msg))
    except actions.ActionError as e:
        return resp(str(e), "warning")
    except Exception as e:
        logger.exception("卡片操作失败")
        return resp(f"操作失败：{e}", "error")

    return resp(f"未知操作：{op}", "error")


def _run_ws() -> None:
    handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(_on_message) \
        .register_p2_card_action_trigger(_on_card_action) \
        .build()
    client = lark.ws.Client(
        config.LARK_APP_ID, config.LARK_APP_SECRET,
        event_handler=handler, domain=config.LARK_DOMAIN, log_level=lark.LogLevel.INFO,
    )
    logger.info("ws 模式启动（长连接），Ctrl+C 退出")
    client.start()


# ======================= 入口 =======================

def main() -> None:
    _resolve_admin_emails()
    if not config.BOT_ADMIN_OPEN_IDS:
        logger.warning("管理员白名单为空：处于绑定模式，给 bot 发任意消息即可获取你的 open_id")
    else:
        logger.info("管理员白名单共 %d 人", len(config.BOT_ADMIN_OPEN_IDS))

    if config.BOT_MODE == "ws":
        _run_ws()
    else:
        from bot import poller
        try:
            poller.run()
        except KeyboardInterrupt:
            logger.info("已停止")


if __name__ == "__main__":
    main()
