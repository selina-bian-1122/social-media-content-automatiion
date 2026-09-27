"""人工提报素材：写入【素材收集】，处理状态「待处理」，下一次素材加工时被 AI 处理（人工提报优先）。"""

import logging
import re

import config
import lark_client

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"^https?://\S+$")


def add(items: list[str], note: str = "") -> int:
    """items 中每一项可以是链接，也可以是一段纯文字素材（没有链接的想法/消息/观点）。"""
    created = 0
    for item in items:
        item = item.strip()
        if not item:
            continue
        if _URL_RE.match(item):
            fields = {"原文链接": {"link": item, "text": item}, "素材描述": note or "人工提报"}
        else:
            fields = {"素材描述": f"{item}\n\n{note}".strip() if note else item}
        fields.update({"来源": "人工提报", "处理状态": "待处理"})

        lark_client.create_record(config.TABLE_IDS["materials"], fields)
        logger.info("已添加人工素材：%s", item[:80])
        created += 1
    return created
