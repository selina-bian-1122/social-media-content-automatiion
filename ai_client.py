import json
import logging

import anthropic
import openai

import config

logger = logging.getLogger(__name__)


def generate(prompt: str, system_prompt: str = "") -> dict | str:
    if config.AI_PROVIDER == "anthropic":
        return _call_anthropic(prompt, system_prompt)
    elif config.AI_PROVIDER == "openai":
        return _call_openai(prompt, system_prompt)
    else:
        raise ValueError(f"Unknown AI_PROVIDER: {config.AI_PROVIDER}")


def _call_anthropic(prompt: str, system_prompt: str) -> dict | str:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, base_url=config.ANTHROPIC_BASE_URL)

    kwargs = {
        "model": config.AI_MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    resp = client.messages.create(**kwargs)
    text = ""
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            text = block.text
            break

    return _try_parse_json(text)


def _call_openai(prompt: str, system_prompt: str) -> dict | str:
    client = openai.OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.completions.create(
        model=config.AI_MODEL,
        messages=messages,
        max_tokens=4096,
    )
    text = resp.choices[0].message.content

    return _try_parse_json(text)


def _try_parse_json(text: str) -> dict | str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # skip ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("AI response is not valid JSON, returning raw text")
        return text
