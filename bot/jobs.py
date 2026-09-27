"""后台任务：批准后的流水线操作在单线程队列里串行执行，避免并发写表。"""

import logging
from concurrent.futures import ThreadPoolExecutor

import notifier
from automations import content_generator, material_processor, rss_fetcher
from bot import cards

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")

# op → (显示名称, 说明)，同时作为「可审批操作」白名单
OPERATIONS = {
    "run_all": ("完整流水线", "RSS 抓取 → 素材加工（AI 判断相关性、生成选题）→ 为已采纳选题生成初稿，完成后推送新选题卡片。"),
    "fetch_rss": ("RSS 抓取", "从 config/topic_domains.yaml 中的 RSS 源抓取新文章写入素材表。"),
    "process_materials": ("素材加工", "对素材表中「待处理」的素材调用 AI 判断相关性，相关的转为选题，并推送选题卡片。"),
    "generate_content": ("初稿生成", "为所有「已采纳」且尚未生成的 选题×账号 组合生成 X 初稿。"),
}


def submit(op: str, chat_id: str, **kwargs) -> None:
    _executor.submit(_run_safely, op, chat_id, kwargs)


def _run_safely(op: str, chat_id: str, kwargs: dict) -> None:
    try:
        summary = _run(op, chat_id, **kwargs)
        if summary:
            notifier.notify(summary, chat_id)
    except Exception as e:
        logger.exception("任务 %s 执行失败", op)
        notifier.notify(f"❌ {OPERATIONS.get(op, (op,))[0]} 执行失败：{e}", chat_id)


def _run(op: str, chat_id: str, topic_ids: list[str] | None = None) -> str:
    content_link = cards.table_link("content", "内容库")

    if op == "fetch_rss":
        n = rss_fetcher.run()
        return f"✅ RSS 抓取完成，新增 {n} 条素材。发送「加工」可继续处理。"

    if op == "process_materials":
        n = material_processor.run()
        pushed = notifier.push_pending_topics(chat_id)
        return f"✅ 素材加工完成：处理 {n} 条，推送 {pushed} 个新选题待筛选。"

    if op == "generate_content":
        n = content_generator.run(topic_ids)
        return f"✅ 初稿生成完成：{n} 篇，状态为「待人工编辑」，请到{content_link}查看。"

    if op == "run_all":
        rss = rss_fetcher.run()
        mat = material_processor.run()
        gen = content_generator.run()
        pushed = notifier.push_pending_topics(chat_id)
        return (f"✅ 完整流水线完成\n"
                f"· RSS 新增素材 {rss} 条\n"
                f"· 素材加工 {mat} 条，推送新选题 {pushed} 个\n"
                f"· 生成初稿 {gen} 篇（{content_link}）")

    raise ValueError(f"未知操作: {op}")
