import argparse
import logging
import sys
import time

import schedule

import notifier
from automations import rss_fetcher, material_processor, content_generator, manual_input

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def run_all(skip_rss: bool = False, push: bool = False,
            limit: int | None = None, only_manual: bool = False):
    logger.info("=== 开始执行全部自动化任务 ===")

    if skip_rss:
        logger.info("--- RSS 抓取（已跳过）---")
    else:
        logger.info("--- RSS 抓取 ---")
        rss_count = rss_fetcher.run()
        logger.info("RSS 抓取完成，新增 %d 条素材", rss_count)

    logger.info("--- 素材加工 ---")
    material_count = material_processor.run(limit=limit, only_manual=only_manual)
    logger.info("素材加工完成，处理 %d 条", material_count)

    logger.info("--- 内容生成 ---")
    content_count = content_generator.run()
    logger.info("内容生成完成，生成 %d 条初稿", content_count)

    if not push:
        logger.info("=== 全部任务执行完毕 ===")
        return

    logger.info("--- 飞书推送 ---")
    try:
        pushed = notifier.push_pending_topics()
        if content_count:
            notifier.notify(f"✅ 定时任务新生成 {content_count} 篇初稿，状态「待人工编辑」。")
        logger.info("推送新选题卡片 %d 个", pushed)
    except Exception as e:
        logger.error("飞书推送失败: %s", e)

    logger.info("=== 全部任务执行完毕 ===")


def main():
    parser = argparse.ArgumentParser(description="OrphLux 海外社媒内容自动化")
    parser.add_argument("--once", action="store_true", help="执行一次全部任务后退出")
    parser.add_argument("--fetch-rss", action="store_true", help="仅执行 RSS 抓取")
    parser.add_argument("--add", nargs="+", metavar="链接或文字",
                        help="人工添加素材到【素材收集】（可多个；链接或一段文字均可），之后执行 --process-materials")
    parser.add_argument("--note", default="", help="配合 --add：给素材附一句说明/想法")
    parser.add_argument("--process-materials", action="store_true", help="仅执行素材加工")
    parser.add_argument("--generate-content", action="store_true", help="仅执行内容生成")
    parser.add_argument("--interval", type=int, default=5, help="轮询间隔（分钟），默认 5")
    parser.add_argument("--skip-rss", action="store_true", help="全流程中跳过 RSS 抓取（只处理素材表已有内容与已采纳选题）")
    parser.add_argument("--push", action="store_true", help="全流程结束后把新选题卡片/结果推送到飞书")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="素材加工每次最多处理 N 条（人工提报优先，其余从新到旧）；默认处理全部")
    parser.add_argument("--only-manual", action="store_true", help="素材加工只处理人工提报的素材，不碰 RSS 素材")
    args = parser.parse_args()
    job = lambda: run_all(skip_rss=args.skip_rss, push=args.push,
                          limit=args.limit, only_manual=args.only_manual)

    if args.add:
        n = manual_input.add(args.add, args.note)
        logger.info("已添加 %d 条人工素材（待处理），下一步：python main.py --process-materials", n)
        return

    if args.fetch_rss:
        rss_fetcher.run()
        return

    if args.process_materials:
        material_processor.run(limit=args.limit, only_manual=args.only_manual)
        return

    if args.generate_content:
        content_generator.run()
        return

    if args.once:
        job()
        return

    # 轮询模式
    logger.info("启动轮询模式，间隔 %d 分钟（Ctrl+C 退出）", args.interval)
    schedule.every(args.interval).minutes.do(job)

    job()  # 启动时立即执行一次

    try:
        while True:
            schedule.run_pending()
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("轮询已停止")


if __name__ == "__main__":
    main()
