import json
import logging

import config
import lark_client
import ai_client

logger = logging.getLogger(__name__)


def run(topic_ids: list[str] | None = None) -> int:
    """为“已采纳”的选题生成初稿；传入 topic_ids 时只处理这些选题。"""
    topics = lark_client.list_all_records(
        config.TABLE_IDS["topics"],
        filter_expr='CurrentValue.[状态] = "已采纳"',
    )
    if topic_ids is not None:
        wanted = set(topic_ids)
        topics = [t for t in topics if t["record_id"] in wanted]

    if not topics:
        logger.info("No adopted topics to generate content for")
        return 0

    existing_combos = _get_existing_topic_account_combos()
    prompt_template = config.load_prompt("content_draft.txt")
    generated = 0

    for topic in topics:
        topic_id = topic["record_id"]
        fields = topic["fields"]

        title = fields.get("标题", "")
        summary = fields.get("AI摘要", "")
        angle = fields.get("建议角度", "")

        # "适配账号" is a Link field — value is a list of record IDs
        account_links = fields.get("适配账号", [])
        if not account_links:
            logger.warning("选题「%s」已采纳但未填写「适配账号」，跳过（请在选题库补填账号）", title)
            continue

        if isinstance(account_links, dict):
            account_links = [account_links]

        account_ids = []
        for link in account_links:
            if isinstance(link, str):
                account_ids.append(link)
            elif isinstance(link, dict):
                ids = link.get("record_ids", [])
                if ids:
                    account_ids.extend(ids)
                else:
                    aid = link.get("record_id", link.get("id", ""))
                    if aid:
                        account_ids.append(aid)

        for account_id in account_ids:
            if not account_id:
                continue

            combo_key = f"{topic_id}:{account_id}"
            if combo_key in existing_combos:
                logger.debug("Content already exists for topic+account: %s", combo_key)
                continue

            account_info = _get_account_info(account_id)
            if not account_info:
                logger.warning("Account %s not found, skipping", account_id)
                continue

            content_record_id = _create_content_record(topic_id, account_id)

            prompt = prompt_template \
                .replace("{{account_name}}", account_info.get("姓名", "")) \
                .replace("{{persona_tags}}", ", ".join(account_info.get("人设定位标签", []))) \
                .replace("{{topic_summary}}", summary) \
                .replace("{{suggested_angle}}", angle) \
                .replace("{{long_form_content}}", "")

            try:
                result = ai_client.generate(prompt)
            except Exception as e:
                logger.error("AI generation failed: %s", e)
                lark_client.update_record(
                    config.TABLE_IDS["content"], content_record_id,
                    {"AI初稿": f"AI generation failed: {e}", "状态": "待人工编辑"},
                )
                generated += 1
                continue

            if isinstance(result, dict):
                body = result.get("body", [])
                if isinstance(body, list):
                    draft_text = "\n\n".join(body)
                else:
                    draft_text = str(body)

                content_type = result.get("content_type", "")
                notes = result.get("notes", "")
                if notes:
                    draft_text += f"\n\n---\nNotes: {notes}"

                content_form_map = {
                    "original": "原创",
                    "retweet_comment": "转发+评论",
                    "quote": "引用",
                }
                content_form = content_form_map.get(content_type, "原创")

                lark_client.update_record(
                    config.TABLE_IDS["content"], content_record_id,
                    {
                        "AI初稿": draft_text,
                        "内容形式": content_form,
                        "状态": "待人工编辑",
                    },
                )
            else:
                lark_client.update_record(
                    config.TABLE_IDS["content"], content_record_id,
                    {"AI初稿": str(result), "状态": "待人工编辑"},
                )

            logger.info("Content generated for '%s' × %s", title, account_info.get("姓名", ""))
            generated += 1

    logger.info("Content generation complete: %d drafts", generated)
    return generated


def _get_existing_topic_account_combos() -> set[str]:
    records = lark_client.list_all_records(config.TABLE_IDS["content"])
    combos = set()
    for r in records:
        topic_link = r["fields"].get("关联选题", [])
        account_link = r["fields"].get("关联账号", [])

        topic_id = _extract_link_id(topic_link)
        account_id = _extract_link_id(account_link)

        if topic_id and account_id:
            combos.add(f"{topic_id}:{account_id}")
    return combos


def _extract_link_id(link_field) -> str:
    if isinstance(link_field, list) and link_field:
        item = link_field[0]
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            ids = item.get("record_ids", [])
            if ids:
                return ids[0]
            return item.get("record_id", item.get("id", ""))
    if isinstance(link_field, str):
        return link_field
    if isinstance(link_field, dict):
        ids = link_field.get("record_ids", [])
        if ids:
            return ids[0]
        return link_field.get("record_id", link_field.get("id", ""))
    return ""


def _get_account_info(account_id: str) -> dict | None:
    try:
        records = lark_client.list_all_records(config.TABLE_IDS["accounts"])
        for r in records:
            if r["record_id"] == account_id:
                fields = r["fields"]
                tags = fields.get("人设定位标签", [])
                if isinstance(tags, list):
                    tag_list = []
                    for t in tags:
                        if isinstance(t, dict):
                            tag_list.append(t.get("text", str(t)))
                        else:
                            tag_list.append(str(t))
                    fields["人设定位标签"] = tag_list
                return fields
    except Exception as e:
        logger.error("Failed to get account info: %s", e)
    return None


def _create_content_record(topic_id: str, account_id: str) -> str:
    return lark_client.create_record(
        config.TABLE_IDS["content"],
        {
            "关联选题": [topic_id],
            "关联账号": [account_id],
            # 只能写表格里已有的选项（生成中/待人工编辑/待审核/已通过），写入不存在的值飞书会自动新建选项
            "状态": "生成中",
        },
    )
