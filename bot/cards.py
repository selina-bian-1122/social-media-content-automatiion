"""飞书消息卡片（JSON 2.0）构造。

所有按钮都通过 behaviors.callback 回传 value，value 中的 "op" 字段决定 bot_listener 的处理分支。
"""

from typing import Any

import config


def plain(value: Any) -> str:
    """把多维表格字段值（文本/富文本/链接/选项）转成纯文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return value.get("text") or value.get("link") or value.get("name") or ""
    if isinstance(value, list):
        # 富文本字段返回的是 [{"type": "text", "text": "..."}, ...]，片段直接拼接；其余（多选等）用顿号分隔
        if value and all(isinstance(v, dict) and "type" in v for v in value):
            return "".join(plain(v) for v in value)
        return "、".join(plain(v) for v in value)
    return str(value)


def table_link(table_key: str, label: str) -> str:
    """生成跳转到多维表格某张表的 markdown 链接；未配置 LARK_BASE_URL 时只返回文字。"""
    if not config.LARK_BASE_URL:
        return label
    return f"[{label}]({config.LARK_BASE_URL}?table={config.TABLE_IDS[table_key]})"


def _text(s: str) -> dict:
    return {"tag": "plain_text", "content": s}


def _md(s: str) -> dict:
    return {"tag": "markdown", "content": s}


def _card(title: str, template: str, elements: list[dict]) -> dict:
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {"title": _text(title), "template": template},
        "body": {"elements": elements},
    }


def _button(label: str, value: dict, type_: str = "default",
            form_submit_name: str | None = None) -> dict:
    btn = {
        "tag": "button",
        "text": _text(label),
        "type": type_,
        "behaviors": [{"type": "callback", "value": value}],
    }
    if form_submit_name:
        btn["name"] = form_submit_name
        btn["form_action_type"] = "submit"
    return btn


def _button_row(buttons: list[dict]) -> dict:
    return {
        "tag": "column_set",
        "flex_mode": "flow",
        "columns": [
            {"tag": "column", "width": "auto", "elements": [b]} for b in buttons
        ],
    }


# ---------- 选题审批 ----------

def _interactive() -> bool:
    return config.BOT_MODE == "ws"


def topic_card(topic: dict, accounts: list[tuple[str, str, str]], code: str) -> dict:
    """待筛选选题卡片。

    ws 模式：选择账号后点「采纳并生成初稿」或「淘汰」；
    poll 模式：无按钮，提示用文字回复「采纳 T3 A1 A2」/「淘汰 T3」。
    accounts: [(账号编号 A1, record_id, 显示名)]
    """
    f = topic["fields"]
    lines = [f"**{plain(f.get('标题')) or '（无标题）'}**"]
    if f.get("AI摘要"):
        lines.append(f"📝 {plain(f.get('AI摘要'))}")
    if f.get("建议角度"):
        lines.append(f"💡 建议角度：{plain(f.get('建议角度'))}")
    meta = []
    if f.get("优先级"):
        meta.append(f"优先级 {plain(f.get('优先级'))}")
    if f.get("行业标签"):
        meta.append(plain(f.get("行业标签")))
    if f.get("来源类型"):
        meta.append(plain(f.get("来源类型")))
    if meta:
        lines.append(f"<font color='grey'>{' · '.join(meta)}</font>")
    link = f.get("原文链接")
    if isinstance(link, dict) and link.get("link"):
        lines.append(f"[查看原文]({link['link']})")

    rid = topic["record_id"]
    elements: list[dict] = [_md("\n".join(lines))]
    title = f"📌 新选题待筛选 · {code}"

    if not _interactive():
        if accounts:
            account_lines = "　".join(f"**{c}** {label}" for c, _, label in accounts)
            elements.append({"tag": "hr"})
            elements.append(_md(
                f"可选账号：{account_lines}\n\n"
                f"回复 `采纳 {code} {accounts[0][0]}`（多个账号用空格分隔，或 `采纳 {code} 全部`）\n"
                f"回复 `淘汰 {code}` 放弃该选题"
            ))
        else:
            elements.append(_md(f"<font color='red'>账号矩阵中没有「启用」的账号。</font>回复 `淘汰 {code}` 可放弃该选题。"))
        return _card(title, "blue", elements)

    if accounts:
        form_elements = [
            {
                "tag": "multi_select_static",
                "name": "accounts",
                "placeholder": _text("选择要发布的账号"),
                "options": [{"text": _text(label), "value": aid} for _, aid, label in accounts],
            },
            _button_row([
                _button("采纳并生成初稿", {"op": "adopt_topic", "topic_id": rid},
                        "primary", form_submit_name="adopt"),
                _button("淘汰", {"op": "reject_topic", "topic_id": rid},
                        "danger", form_submit_name="reject"),
            ]),
        ]
        elements.append({"tag": "form", "name": "topic_form", "elements": form_elements})
    else:
        elements.append(_md("<font color='red'>账号矩阵中没有「启用」的账号，只能淘汰或去表格里处理。</font>"))
        elements.append(_button_row([
            _button("淘汰", {"op": "reject_topic", "topic_id": rid}, "danger"),
        ]))

    return _card(title, "blue", elements)


# ---------- 通用审批 ----------

def approval_card(title: str, description: str, code: str) -> dict:
    """需要人工批准才执行的操作（code 为待批准编号 R#）。"""
    header = f"🔐 待批准 {code}：{title}"
    if not _interactive():
        return _card(header, "orange", [
            _md(description),
            {"tag": "hr"},
            _md(f"回复 `批准 {code}` 执行，或 `取消 {code}`"),
        ])
    return _card(header, "orange", [
        _md(description),
        _button_row([
            _button("批准执行", {"op": "approve", "code": code}, "primary"),
            _button("取消", {"op": "cancel", "code": code}),
        ]),
    ])


def result_card(title: str, template: str, content: str) -> dict:
    """点击后替换原卡片的终态（不再有按钮，避免重复点击）。"""
    return _card(title, template, [_md(content)])
