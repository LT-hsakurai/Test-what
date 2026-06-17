"""
Step 1-3: Playwright でレスポンスを傍受し、p-town.dmm.com 由来の JSON を
captures/ に保存してエンドポイント一覧を出力する。

使い方:
  pip install playwright
  playwright install chromium
  python step1_capture.py
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urlencode

from playwright.async_api import async_playwright, Request, Response

CAPTURES_DIR = Path(__file__).parent / "captures"
CAPTURES_DIR.mkdir(exist_ok=True)

TARGET_PAGES = [
    "https://p-town.dmm.com/machine_borders",
    "https://p-town.dmm.com/machines",
]

HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.6367.91 Safari/537.36"
    ),
    "accept-language": "ja,en-US;q=0.9,en;q=0.8",
}

captured: list[dict] = []

def safe_filename(url: str) -> str:
    """URL を安全なファイル名に変換する"""
    parsed = urlparse(url)
    name = (parsed.path + ("?" + parsed.query if parsed.query else ""))
    name = re.sub(r"[^\w\-_.]", "_", name).strip("_")
    return name[:120] or "root"


async def handle_response(response: Response) -> None:
    url = response.url
    if "p-town.dmm.com" not in url:
        return
    ct = response.headers.get("content-type", "")
    if "json" not in ct:
        return

    try:
        body = await response.json()
    except Exception:
        try:
            text = await response.text()
            body = json.loads(text)
        except Exception:
            return

    entry = {
        "url": url,
        "status": response.status,
        "content_type": ct,
        "body": body,
    }
    captured.append(entry)

    fname = safe_filename(url) + ".json"
    out_path = CAPTURES_DIR / fname
    # 同名ファイルが既にあれば連番にする
    counter = 0
    while out_path.exists():
        counter += 1
        out_path = CAPTURES_DIR / f"{safe_filename(url)}_{counter}.json"

    out_path.write_text(json.dumps(body, ensure_ascii=False, indent=2))
    print(f"  [SAVED] {url}\n         -> {out_path.name}")


async def visit_page(page, url: str) -> None:
    print(f"\n=== Visiting: {url} ===")
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    # JS レンダリング完了を少し待つ
    await page.wait_for_timeout(5_000)
    # スクロールして遅延ロードを誘発
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(3_000)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(2_000)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            extra_http_headers=HEADERS,
            viewport={"width": 390, "height": 844},  # iPhone 14 相当
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
        )
        page = await context.new_page()
        page.on("response", handle_response)

        for url in TARGET_PAGES:
            try:
                await visit_page(page, url)
            except Exception as e:
                print(f"  [ERROR] {url}: {e}", file=sys.stderr)

        await browser.close()

    # ─── 結果レポート ───────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"キャプチャ完了: {len(captured)} 件")
    print("=" * 60)
    if not captured:
        print("JSON レスポンスが1件も取得できませんでした。")
        print("Cloudflare 等のボット検知の可能性があります。")
        return

    print("\n取得URL一覧:")
    for i, e in enumerate(captured, 1):
        body = e["body"]
        top_keys = list(body.keys())[:5] if isinstance(body, dict) else f"array[{len(body)}]"
        print(f"  {i:3}. [{e['status']}] {e['url']}")
        print(f"       top-level keys: {top_keys}")

    # ─── 目的4項目のキーワードで絞り込み ─────────────────────
    keywords = ["border", "first_hit", "probability", "kakuritsu",
                "kitai", "taisenka", "initial", "spec", "machine"]
    print("\n--- 目的データ候補 ---")
    for e in captured:
        body = e["body"]
        body_str = json.dumps(body, ensure_ascii=False).lower()
        if any(k in body_str for k in keywords):
            print(f"  ** {e['url']}")
            if isinstance(body, dict):
                for k, v in list(body.items())[:8]:
                    print(f"     {k}: {str(v)[:80]}")
            elif isinstance(body, list) and body:
                print(f"     [0]: {json.dumps(body[0], ensure_ascii=False)[:200]}")

    # ─── captures/ に URL 一覧も保存 ─────────────────────────
    summary = [{"url": e["url"], "status": e["status"]} for e in captured]
    (CAPTURES_DIR / "_url_list.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    print(f"\ncaptures/_url_list.json に URL 一覧を保存しました。")
    print("captures/ フォルダの内容を共有してください。")


if __name__ == "__main__":
    asyncio.run(main())
