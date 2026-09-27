import logging

import httpx
from readability import Document

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MAX_CONTENT_LENGTH = 8000


def fetch_article(url: str, timeout: float = 15.0) -> dict:
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url, headers=_HEADERS)
            resp.raise_for_status()

        doc = Document(resp.text)
        title = doc.short_title() or ""
        content = doc.summary(html_partial=True)

        # strip HTML tags for plain text
        import re
        clean = re.sub(r"<[^>]+>", " ", content)
        clean = re.sub(r"\s+", " ", clean).strip()

        if len(clean) > MAX_CONTENT_LENGTH:
            clean = clean[:MAX_CONTENT_LENGTH] + "..."

        return {
            "success": True,
            "title": title,
            "content": clean,
            "url": url,
        }

    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return {
            "success": False,
            "title": "",
            "content": "",
            "url": url,
            "error": str(e),
        }
