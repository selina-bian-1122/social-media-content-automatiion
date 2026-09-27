"""连通性测试脚本：验证 Lark API、AI API、网页抓取是否正常工作。"""

import sys

import config
import lark_client
import ai_client
import web_scraper


def check(label: str, func):
    try:
        func()
        print(f"  ✓ {label}")
        return True
    except Exception as e:
        print(f"  ✗ {label}: {e}")
        return False


def test_lark_tables():
    tables = {
        "素材收集": config.TABLE_IDS["materials"],
        "账号矩阵": config.TABLE_IDS["accounts"],
        "选题库": config.TABLE_IDS["topics"],
        "内容库": config.TABLE_IDS["content"],
    }

    ok = True
    for name, table_id in tables.items():
        def _read(tid=table_id):
            records = lark_client.list_all_records(tid)
            return len(records)

        try:
            count = _read()
            print(f"  ✓ {name}表读取成功，共 {count} 条记录")
        except Exception as e:
            print(f"  ✗ {name}表读取失败: {e}")
            ok = False
    return ok


def test_ai():
    result = ai_client.generate("请回复 OK（仅两个字母，不要其他内容）")
    text = result if isinstance(result, str) else str(result)
    if "OK" in text.upper():
        print(f"  ✓ AI API ({config.AI_PROVIDER}/{config.AI_MODEL}) 调用成功")
        return True
    print(f"  ✗ AI API 返回异常: {text[:100]}")
    return False


def test_scraper():
    url = "https://techcrunch.com/category/artificial-intelligence/"
    result = web_scraper.fetch_article(url, timeout=20.0)
    if result.get("success") and len(result.get("content", "")) > 100:
        print(f"  ✓ 网页抓取成功（{len(result['content'])} 字符）")
        return True
    print(f"  ✗ 网页抓取失败: {result.get('error', '内容为空')}")
    return False


def main():
    print("\n========== OrphLux 连通性测试 ==========\n")
    results = []

    print("[1/3] Lark Bitable API")
    results.append(test_lark_tables())

    print(f"\n[2/3] AI API ({config.AI_PROVIDER})")
    results.append(test_ai())

    print("\n[3/3] 网页抓取")
    results.append(test_scraper())

    print("\n========================================")
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"全部通过 ({passed}/{total})")
    else:
        print(f"通过 {passed}/{total}，请检查失败项")
        sys.exit(1)


if __name__ == "__main__":
    main()
