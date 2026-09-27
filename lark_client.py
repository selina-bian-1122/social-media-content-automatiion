import json
import logging
from typing import Any

import httpx
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    AppTableRecord,
    CreateAppTableRecordRequest,
    GetAppTableRecordRequest,
    ListAppTableRecordRequest,
    UpdateAppTableRecordRequest,
)
from lark_oapi.api.contact.v3 import BatchGetIdUserRequest, BatchGetIdUserRequestBody
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

import config

logger = logging.getLogger(__name__)

_client: lark.Client | None = None


def _get_client() -> lark.Client:
    global _client
    if _client is None:
        _client = lark.Client.builder() \
            .app_id(config.LARK_APP_ID) \
            .app_secret(config.LARK_APP_SECRET) \
            .domain(config.LARK_DOMAIN) \
            .log_level(lark.LogLevel.WARNING) \
            .build()
    return _client


def list_records(
    table_id: str,
    filter_expr: str | None = None,
    page_size: int = 100,
    page_token: str | None = None,
) -> dict[str, Any]:
    req = ListAppTableRecordRequest.builder() \
        .app_token(config.LARK_BASE_APP_TOKEN) \
        .table_id(table_id) \
        .page_size(page_size)

    if filter_expr:
        req = req.filter(filter_expr)
    if page_token:
        req = req.page_token(page_token)

    resp = _get_client().bitable.v1.app_table_record.list(req.build())

    if not resp.success():
        logger.error("list_records failed: %s %s", resp.code, resp.msg)
        raise RuntimeError(f"Lark API error: {resp.code} {resp.msg}")

    items = resp.data.items or []
    records = []
    for item in items:
        records.append({
            "record_id": item.record_id,
            "fields": item.fields,
        })

    return {
        "records": records,
        "has_more": resp.data.has_more,
        "page_token": resp.data.page_token,
        "total": resp.data.total,
    }


def create_record(table_id: str, fields: dict[str, Any]) -> str:
    req = CreateAppTableRecordRequest.builder() \
        .app_token(config.LARK_BASE_APP_TOKEN) \
        .table_id(table_id) \
        .request_body(
            AppTableRecord.builder()
            .fields(fields)
            .build()
        ) \
        .build()

    resp = _get_client().bitable.v1.app_table_record.create(req)

    if not resp.success():
        logger.error("create_record failed: %s %s", resp.code, resp.msg)
        raise RuntimeError(f"Lark API error: {resp.code} {resp.msg}")

    return resp.data.record.record_id


def update_record(table_id: str, record_id: str, fields: dict[str, Any]) -> None:
    req = UpdateAppTableRecordRequest.builder() \
        .app_token(config.LARK_BASE_APP_TOKEN) \
        .table_id(table_id) \
        .record_id(record_id) \
        .request_body(
            AppTableRecord.builder()
            .fields(fields)
            .build()
        ) \
        .build()

    resp = _get_client().bitable.v1.app_table_record.update(req)

    if not resp.success():
        logger.error("update_record failed: %s %s", resp.code, resp.msg)
        raise RuntimeError(f"Lark API error: {resp.code} {resp.msg}")


def get_record(table_id: str, record_id: str) -> dict[str, Any]:
    req = GetAppTableRecordRequest.builder() \
        .app_token(config.LARK_BASE_APP_TOKEN) \
        .table_id(table_id) \
        .record_id(record_id) \
        .build()

    resp = _get_client().bitable.v1.app_table_record.get(req)

    if not resp.success():
        logger.error("get_record failed: %s %s", resp.code, resp.msg)
        raise RuntimeError(f"Lark API error: {resp.code} {resp.msg}")

    return {"record_id": resp.data.record.record_id, "fields": resp.data.record.fields}


def get_open_ids_by_emails(emails: list[str]) -> dict[str, str]:
    """邮箱 → open_id；查不到的邮箱不出现在结果中。需要 contact:user.id:readonly 权限。"""
    req = BatchGetIdUserRequest.builder() \
        .user_id_type("open_id") \
        .request_body(BatchGetIdUserRequestBody.builder().emails(emails).build()) \
        .build()

    resp = _get_client().contact.v3.user.batch_get_id(req)

    if not resp.success():
        logger.error("get_open_ids_by_emails failed: %s %s", resp.code, resp.msg)
        raise RuntimeError(f"Lark API error: {resp.code} {resp.msg}")

    return {
        u.email.lower(): u.user_id
        for u in (resp.data.user_list or [])
        if u.email and u.user_id
    }


def send_message(receive_id: str, msg_type: str, content: dict,
                 receive_id_type: str = "chat_id") -> str:
    req = CreateMessageRequest.builder() \
        .receive_id_type(receive_id_type) \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type(msg_type)
            .content(json.dumps(content, ensure_ascii=False))
            .build()
        ) \
        .build()

    resp = _get_client().im.v1.message.create(req)

    if not resp.success():
        logger.error("send_message failed: %s %s", resp.code, resp.msg)
        raise RuntimeError(f"Lark API error: {resp.code} {resp.msg}")

    return resp.data.message_id


def send_text(chat_id: str, text: str) -> str:
    return send_message(chat_id, "text", {"text": text})


def send_card(chat_id: str, card: dict) -> str:
    return send_message(chat_id, "interactive", card)


def send_group_message(chat_id: str, text: str) -> None:
    send_text(chat_id, text)


def list_all_records(table_id: str, filter_expr: str | None = None) -> list[dict]:
    all_records = []
    page_token = None

    while True:
        result = list_records(table_id, filter_expr, page_token=page_token)
        all_records.extend(result["records"])
        if not result["has_more"]:
            break
        page_token = result["page_token"]

    return all_records
