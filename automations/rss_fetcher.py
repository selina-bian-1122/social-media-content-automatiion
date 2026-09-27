import calendar
import logging
import os
import time

import feedparser

import config
import lark_client

logger = logging.getLogger(__name__)


# 每个源只看最新的 N 条：已抓过的跳过但同样计入名额，所以重复运行不会越翻越旧
MAX_PER_FEED = int(os.getenv("RSS_MAX_PER_FEED", "5"))
# 只收最近 N 天发布的文章（源里没有发布时间的条目不受此限制）
MAX_AGE_DAYS = float(os.getenv("RSS_MAX_AGE_DAYS", "3"))


def _too_old(entry) -> bool:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return False
    return time.time() - calendar.timegm(published) > MAX_AGE_DAYS * 86400


def run() -> int:
    domains_cfg = config.load_domains_config()
    feeds = domains_cfg.get("rss_feeds") or []
    active_feeds = [f for f in feeds if f.get("url")]

    if not active_feeds:
        logger.info("No RSS feeds configured, skipping")
        return 0

    existing_urls = _get_existing_urls()
    new_count = 0

    for feed_cfg in active_feeds:
        name = feed_cfg["name"]
        url = feed_cfg["url"]
        feed_count = 0
        logger.info("Fetching RSS: %s (%s)", name, url)

        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            logger.error("Failed to parse RSS %s: %s", name, e)
            continue

        for entry in parsed.entries[:MAX_PER_FEED]:
            link = entry.get("link", "")
            if not link or link in existing_urls or _too_old(entry):
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "")
            description = f"[RSS: {name}] {title}"
            if summary:
                description += f" — {summary[:100]}"

            try:
                lark_client.create_record(
                    config.TABLE_IDS["materials"],
                    {
                        "原文链接": {"link": link, "text": link},
                        "素材描述": description,
                        "来源": "RSS抓取",
                        "处理状态": "待处理",
                    },
                )
                existing_urls.add(link)
                new_count += 1
                feed_count += 1
                logger.info("New material from RSS: %s", title)
            except Exception as e:
                logger.error("Failed to create material record: %s", e)

    logger.info("RSS fetch complete: %d new materials", new_count)
    return new_count


def _get_existing_urls() -> set[str]:
    records = lark_client.list_all_records(config.TABLE_IDS["materials"])
    urls = set()
    for r in records:
        url_field = r["fields"].get("原文链接")
        if url_field:
            if isinstance(url_field, dict):
                urls.add(url_field.get("link", ""))
            elif isinstance(url_field, str):
                urls.add(url_field)
    return urls
