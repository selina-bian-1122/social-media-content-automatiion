"""⑥ 自动发布（预留接口，默认关闭）：把【内容库】「已通过」的定稿发到 X，回填「发布链接」「实际发布时间」并改为「已发布」。

开启步骤（未来接入 X API 时）：
  1. 实现 XApiPublisher.publish()（X API v2: POST /2/tweets，需每个账号的 user context 授权）
  2. .env 设置 AUTO_PUBLISH=true
未开启时 run() 直接返回 0，发布仍由人工完成：在 X 发布 → 回填「发布链接」→ 状态改「已发布」。
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import config
import lark_client

logger = logging.getLogger(__name__)

# 发布成功但回写表格失败时，靠本地台账避免下一轮重复发帖
_LEDGER_PATH = config.STATE_DIR / "published.json"


@dataclass
class PublishResult:
    post_id: str
    url: str


class Publisher(Protocol):
    def publish(self, text: str, account: dict) -> PublishResult:
        """发布一条内容；account 为【账号矩阵】该账号的字段（编号、姓名、平台…）。失败时抛异常。"""
        ...


class XApiPublisher:
    """X API v2 发布（待实现）。

    建议实现要点：
    - 凭证按账号「编号」从 .env 读取，如 X_ACCOUNT_1_ACCESS_TOKEN / X_ACCOUNT_1_ACCESS_SECRET（OAuth 1.0a）
      或 OAuth 2.0 user token；应用级 X_API_KEY / X_API_SECRET 放 config.py
    - POST https://api.x.com/2/tweets  body: {"text": text}，返回 data.id
    - url = f"https://x.com/{username}/status/{post_id}"
    - 超过 280 字符需拆成 thread（reply.in_reply_to_tweet_id），或在此处直接报错交给人工
    """

    def publish(self, text: str, account: dict) -> PublishResult:
        raise NotImplementedError("X API 发布尚未实现，请先实现 automations/publisher.py 中的 XApiPublisher.publish()")


def run(publisher: Publisher | None = None) -> int:
    """发布所有「已通过」且尚未发布的内容，返回成功发布条数。"""
    if not config.AUTO_PUBLISH:
        logger.info("自动发布未开启（AUTO_PUBLISH=false），「已通过」内容请人工发布")
        return 0

    publisher = publisher or XApiPublisher()
    records = lark_client.list_all_records(
        config.TABLE_IDS["content"], filter_expr='CurrentValue.[状态] = "已通过"',
    )
    ledger = _load_ledger()
    published = 0

    for r in records:
        record_id, fields = r["record_id"], r["fields"]

        if fields.get("发布链接"):
            logger.info("内容 %s 已有「发布链接」（可能已人工发布），跳过；请把状态改为「已发布」", record_id)
            continue

        text = _text(fields.get("定稿文案")).strip()
        if not text:
            logger.warning("内容 %s 已通过但「定稿文案」为空，跳过", record_id)
            continue

        if record_id in ledger:
            result = PublishResult(**ledger[record_id])
            logger.info("内容 %s 此前已发布成功但未回写表格，仅补写：%s", record_id, result.url)
        else:
            account = _get_account(fields.get("关联账号"))
            if account is None:
                logger.warning("内容 %s 找不到「关联账号」，跳过", record_id)
                continue
            try:
                result = publisher.publish(text, account)
            except NotImplementedError:
                raise
            except Exception as e:
                # 保持「已通过」，下一轮重试
                logger.error("内容 %s 发布失败: %s", record_id, e)
                continue
            ledger[record_id] = {"post_id": result.post_id, "url": result.url}
            _save_ledger(ledger)

        lark_client.update_record(
            config.TABLE_IDS["content"], record_id,
            {
                "状态": "已发布",
                "发布链接": {"link": result.url, "text": result.url},
                "实际发布时间": int(time.time() * 1000),
            },
        )
        ledger.pop(record_id, None)
        _save_ledger(ledger)
        published += 1
        logger.info("内容 %s 已发布：%s", record_id, result.url)

    logger.info("自动发布完成：%d 条", published)
    return published


def _text(value) -> str:
    """定稿文案可能是纯文本或富文本片段列表。"""
    if isinstance(value, list):
        return "".join(v.get("text", "") if isinstance(v, dict) else str(v) for v in value)
    return value or ""


def _get_account(link_field) -> dict | None:
    ids = []
    for item in link_field if isinstance(link_field, list) else [link_field]:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            ids.extend(item.get("record_ids") or [item.get("record_id", "")])
    ids = [i for i in ids if i]
    if not ids:
        return None
    return lark_client.get_record(config.TABLE_IDS["accounts"], ids[0])["fields"]


def _load_ledger() -> dict:
    try:
        return json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _save_ledger(ledger: dict) -> None:
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
