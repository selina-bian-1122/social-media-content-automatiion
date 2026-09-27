"""命令行操作多维表格（不依赖 bot 收消息，与 bot 共用同一套逻辑与编号）。

  python ops.py status                  各环节待办数量
  python ops.py topics                  列出待筛选选题（T#）和可用账号（A#）
  python ops.py adopt T86 A1 A2         采纳选题并立即生成初稿（或 adopt T86 all）
  python ops.py reject T79              淘汰选题
T/A 编号就是选题库、账号矩阵里「编号」列（自动编号，永久不变）的数字。
  python ops.py add <URL> [--note 说明]  提交素材到素材表
  python ops.py fetch | process | generate | run
                                        RSS 抓取 / 素材加工 / 初稿生成 / 完整流水线
加 --push 时，新选题卡片和结果也会推送到飞书（LARK_BOT_CHAT_ID）。
"""

import argparse
import logging
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 控制台打印 emoji

import config
import lark_client
import notifier
from automations import manual_input
from bot import actions, cards, codes, commands, jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")


def cmd_status(_):
    print(commands._status_summary())


def cmd_topics(_):
    topics = lark_client.list_all_records(
        config.TABLE_IDS["topics"], filter_expr='CurrentValue.[状态] = "待筛选"',
    )
    accounts = codes.active_accounts()
    topics.sort(key=lambda t: int(cards.plain(t["fields"].get("编号")) or 0))
    print(f"\n待筛选选题 {len(topics)} 个（T 编号 = 选题库「编号」列）：")
    for t in topics:
        f = t["fields"]
        print(f"\n  [{codes.topic_code(t)}] {cards.plain(f.get('标题'))}"
              f"  （优先级 {cards.plain(f.get('优先级')) or '-'}）")
        if f.get("AI摘要"):
            print(f"       摘要：{cards.plain(f.get('AI摘要'))}")
        if f.get("建议角度"):
            print(f"       角度：{cards.plain(f.get('建议角度'))}")
    print("\n可用账号（A 编号 = 账号矩阵「编号」列）：" + (
        "  ".join(f"[{c}] {label}" for c, _, label in accounts) or "无（账号矩阵没有「启用」账号）"))
    print("\n下一步：python ops.py adopt T<编号> A<编号> …   或   python ops.py reject T<编号>")


def cmd_adopt(args):
    topic_id = codes.resolve_topic(args.topic)
    account_ids = codes.resolve_accounts(" ".join(args.accounts))
    print(actions.adopt_topic(topic_id, account_ids, config.LARK_BOT_CHAT_ID))


def cmd_reject(args):
    print(actions.reject_topic(codes.resolve_topic(args.topic)))


def cmd_add(args):
    manual_input.add([args.url], args.note)
    print(f"✅ 已写入素材表（待处理）：{args.url}\n下一步：python ops.py process")


def _pipeline(op):
    def run(_):
        print(jobs._run(op, config.LARK_BOT_CHAT_ID))
        if op in ("process_materials", "run_all"):
            print("查看新选题：python ops.py topics")
    return run


def main():
    parser = argparse.ArgumentParser(description="OrphLux 内容自动化 · 命令行操作")
    parser.add_argument("--push", action="store_true", help="同时把结果/选题卡片推送到飞书")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("topics").set_defaults(func=cmd_topics)
    p = sub.add_parser("adopt"); p.add_argument("topic"); p.add_argument("accounts", nargs="+")
    p.set_defaults(func=cmd_adopt)
    p = sub.add_parser("reject"); p.add_argument("topic"); p.set_defaults(func=cmd_reject)
    p = sub.add_parser("add"); p.add_argument("url"); p.add_argument("--note", default="")
    p.set_defaults(func=cmd_add)
    for name, op in [("fetch", "fetch_rss"), ("process", "process_materials"),
                     ("generate", "generate_content"), ("run", "run_all")]:
        sub.add_parser(name).set_defaults(func=_pipeline(op))

    args = parser.parse_args()

    # 命令行里同步执行（不走 bot 的后台队列），默认不往飞书推送
    jobs.submit = lambda op, chat_id, **kw: print(jobs._run(op, chat_id, **kw))
    if not args.push:
        notifier.push_pending_topics = lambda *a, **kw: 0
        notifier.notify = lambda *a, **kw: None

    try:
        args.func(args)
    except actions.ActionError as e:
        print(f"⚠️ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
