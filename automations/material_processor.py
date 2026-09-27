import json
import logging

import config
import lark_client
import ai_client
import web_scraper

logger = logging.getLogger(__name__)


def run(limit: int | None = None, only_manual: bool = False) -> int:
    """处理待处理素材。

    limit：本次最多处理几条（None = 全部）；only_manual：只处理人工提报的素材。
    顺序：人工提报优先，其余按提交时间从新到旧——限量时先处理最新的。
    """
    # 「待处理」或处理状态留空（在表格里手动添加时常忘记选）都视为待处理；至少要有链接或描述
    materials = [
        m for m in lark_client.list_all_records(config.TABLE_IDS["materials"])
        if (m["fields"].get("处理状态") in (None, "", "待处理"))
        and (m["fields"].get("原文链接") or m["fields"].get("素材描述"))
    ]
    if only_manual:
        materials = [m for m in materials if (m["fields"].get("来源") or "人工提报") == "人工提报"]
    materials.sort(key=lambda m: (
        (m["fields"].get("来源") or "人工提报") != "人工提报",
        -int(m["fields"].get("提交时间") or 0),
    ))

    if not materials:
        logger.info("No pending materials to process")
        return 0

    total = len(materials)
    if limit is not None and limit < total:
        materials = materials[:limit]
    logger.info("待处理素材共 %d 条，本次处理 %d 条", total, len(materials))

    domains_cfg = config.load_domains_config()
    prompt_template = config.load_prompt("material_to_topic.txt")
    min_score = domains_cfg.get("filters", {}).get("min_relevance_score", 0.6)
    domains_text = json.dumps(domains_cfg.get("domains", []), ensure_ascii=False, indent=2)

    processed = 0
    for mat in materials:
        record_id = mat["record_id"]
        fields = mat["fields"]

        url_field = fields.get("原文链接", "")
        if isinstance(url_field, dict):
            url = url_field.get("link", "")
        else:
            url = str(url_field)

        description = _plain(fields.get("素材描述"))
        source = fields.get("来源") or "人工提报"

        logger.info("Processing material: %s", url or description[:50])

        article = {"content": "", "title": ""}
        if url:
            article = web_scraper.fetch_article(url)

        prompt = prompt_template \
            .replace("{{url}}", url) \
            .replace("{{article_title}}", article.get("title", "")) \
            .replace("{{article_content}}", article.get("content", "")[:6000]) \
            .replace("{{description}}", description) \
            .replace("{{domains_config}}", domains_text) \
            .replace("{{min_relevance_score}}", str(min_score))

        try:
            result = ai_client.generate(prompt)
        except Exception as e:
            logger.error("AI call failed for material %s: %s", record_id, e)
            continue

        # 标题优先用网页抓到的原标题（不会编造），抓不到再用 AI 给的；回写进「素材描述」方便在表格里辨认。
        # 正文太短多半是被登录墙/反爬拦下，此时页面标题常是站点名，不可信
        scraped_title = article.get("title", "") if len(article.get("content", "")) >= 200 else ""
        ai_title = result.get("material_title", "") if isinstance(result, dict) else ""
        title = str(scraped_title or ai_title or "").strip()
        desc_update = _titled_description(description, title) if url else {}

        if not isinstance(result, dict):
            logger.warning("AI returned non-JSON for material %s, skipping", record_id)
            lark_client.update_record(
                config.TABLE_IDS["materials"], record_id,
                {"处理状态": "已跳过", "跳过原因": "AI response parse error", **desc_update},
            )
            processed += 1
            continue

        relevant = result.get("relevant", False)
        score = result.get("relevance_score", 0)

        if relevant and score >= min_score:
            topic_data = result.get("topic", {})
            _create_topic(record_id, topic_data, url, source, desc_update)
        else:
            skip_reason = result.get("skip_reason", f"Relevance score {score:.2f} below threshold")
            lark_client.update_record(
                config.TABLE_IDS["materials"], record_id,
                {"处理状态": "已跳过", "跳过原因": skip_reason, **desc_update},
            )

        processed += 1

    logger.info("Material processing complete: %d processed", processed)
    return processed


def _create_topic(material_record_id: str, topic_data: dict, url: str, source: str,
                  desc_update: dict) -> None:
    source_type_map = {
        "人工提报": "员工提报",
        "RSS抓取": "RSS",
        "Google Alerts": "Google Alerts",
    }

    fields = {
        "标题": topic_data.get("title", ""),
        "来源类型": source_type_map.get(source, topic_data.get("source_type", "员工提报")),
        "AI摘要": topic_data.get("summary", ""),
        "建议角度": topic_data.get("suggested_angles", ""),
        "优先级": _map_priority(topic_data.get("priority", "medium")),
        "状态": "待筛选",
        "创建方式": "AI自动",
    }

    if url:
        fields["原文链接"] = {"link": url, "text": url}

    tags = topic_data.get("industry_tags", [])
    if tags:
        fields["行业标签"] = tags

    try:
        topic_record_id = lark_client.create_record(config.TABLE_IDS["topics"], fields)

        lark_client.update_record(
            config.TABLE_IDS["materials"], material_record_id,
            {
                "处理状态": "已转选题",
                "转入选题": [topic_record_id],
                **desc_update,
            },
        )
        logger.info("Topic created: %s", fields["标题"])
    except Exception as e:
        logger.error("Failed to create topic: %s", e)


# 人工提报时没写备注会自动填这些占位文字，它们不携带信息，有标题时直接替换掉
_PLACEHOLDER_DESCRIPTIONS = {"", "人工提报", "飞书 bot 提报"}


def _titled_description(description: str, title: str) -> dict:
    """返回需要回写的 {"素材描述": ...}；没有标题或描述里已含标题（如 RSS 素材）时返回空 dict。"""
    if not title or title in description:
        return {}
    if description.strip() in _PLACEHOLDER_DESCRIPTIONS:
        return {"素材描述": title}
    return {"素材描述": f"{title}\n{description}"}


def _plain(value) -> str:
    """文本字段可能返回字符串，也可能是富文本片段列表 [{"type": "text", "text": ...}]。"""
    if isinstance(value, list):
        return "".join(v.get("text", "") if isinstance(v, dict) else str(v) for v in value)
    return str(value or "")


def _map_priority(priority: str) -> str:
    mapping = {"high": "高", "medium": "中", "low": "低", "高": "高", "中": "中", "低": "低"}
    return mapping.get(priority.lower(), "中")
