"""
Step 4-5: httpx で DMM ぱちタウン API を直接叩き、全機種スペックを CSV に出力する。

・step1_capture.py で取得した captures/_url_list.json を参照して
  API_BASE / BORDERS_PATH / MACHINES_PATH を埋めてから実行する。

取得項目:
  機種名 / ボーダー / 初当たり期待出玉 / 大当たり確率

使い方:
  pip install httpx pandas
  python step4_scraper.py

出力:
  machines.csv
"""

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

# ─── 設定 ────────────────────────────────────────────────────────────────────
# step1_capture.py の結果を見て適宜修正する

API_BASE = "https://p-town.dmm.com"          # API ベース URL
BORDERS_PATH = "/api/v1/machine_borders"     # ボーダー一覧エンドポイント (推定)
MACHINES_PATH = "/api/v1/machines"           # 機種一覧エンドポイント (推定)

PAGE_SIZE = 100        # 1リクエストあたりの件数
SLEEP_SEC = 1.0        # リクエスト間隔 (秒)
MAX_PAGES  = 500       # 無限ループ防止
OUTPUT_CSV = Path(__file__).parent / "machines.csv"

# キー名マッピング (実際の JSON キーを確認後に修正)
# { "出力列名": ["候補キー1", "候補キー2", ...] }
KEY_MAP: dict[str, list[str]] = {
    "機種名":           ["name", "machine_name", "title"],
    "ボーダー":         ["border", "border_value", "taisen_border"],
    "初当たり期待出玉": ["first_hit_balls", "kitai_dedama", "expected_balls", "initial_hit_balls"],
    "大当たり確率":     ["probability", "kakuritsu", "big_bonus_probability", "first_hit_rate"],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.6367.91 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://p-town.dmm.com/",
    "Origin": "https://p-town.dmm.com",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def find_value(record: dict, keys: list[str]) -> Any:
    """候補キーを順に探し最初に見つかった値を返す。ネストも1段階探索する。"""
    for k in keys:
        if k in record:
            return record[k]
    # 値がdictのフィールド内を1段深く探す
    for v in record.values():
        if isinstance(v, dict):
            for k in keys:
                if k in v:
                    return v[k]
    return None


def extract_list(body: Any, path_hint: str = "") -> list[dict]:
    """
    レスポンス全体から機種レコードのリストを探す。
    {"data": [...]} / {"machines": [...]} / [...] などに対応。
    """
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for candidate in ["data", "results", "machines", "items", "list", "borders"]:
            if candidate in body and isinstance(body[candidate], list):
                return body[candidate]
        # ネスト1段
        for v in body.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def fetch_page(client: httpx.Client, url: str, params: dict) -> dict | list | None:
    """1ページ分を取得して JSON を返す。失敗時は None。"""
    try:
        r = client.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        print(f"  HTTP {e.response.status_code}: {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        return None


def detect_pagination(body: Any) -> tuple[int | None, int | None]:
    """
    レスポンスからページング情報を抽出。
    (total_pages, total_count) を返す。不明なら None。
    """
    if not isinstance(body, dict):
        return None, None
    total = body.get("total") or body.get("total_count") or body.get("count")
    pages = body.get("total_pages") or body.get("last_page") or body.get("pages")
    return pages, total


# ─── メイン ─────────────────────────────────────────────────────────────────

def scrape_borders(client: httpx.Client) -> dict[int, dict]:
    """ボーダー情報を {machine_id: record} で返す。"""
    borders: dict[int, dict] = {}
    print(f"\n[1] ボーダー取得: {API_BASE}{BORDERS_PATH}")
    for page in range(1, MAX_PAGES + 1):
        params = {"page": page, "per_page": PAGE_SIZE, "limit": PAGE_SIZE}
        body = fetch_page(client, API_BASE + BORDERS_PATH, params)
        if body is None:
            break
        records = extract_list(body)
        if not records:
            break
        for rec in records:
            mid = rec.get("machine_id") or rec.get("id")
            if mid is not None:
                borders[int(mid)] = rec
        total_pages, total = detect_pagination(body)
        print(f"  page {page}/{total_pages or '?'}  cumulative: {len(borders)}")
        if total_pages and page >= total_pages:
            break
        if len(records) < PAGE_SIZE:
            break
        time.sleep(SLEEP_SEC)
    print(f"  -> {len(borders)} 機種分のボーダー取得完了")
    return borders


def scrape_machines(client: httpx.Client) -> list[dict]:
    """機種一覧を取得して生レコードのリストを返す。"""
    machines: list[dict] = []
    print(f"\n[2] 機種一覧取得: {API_BASE}{MACHINES_PATH}")
    for page in range(1, MAX_PAGES + 1):
        params = {"page": page, "per_page": PAGE_SIZE, "limit": PAGE_SIZE}
        body = fetch_page(client, API_BASE + MACHINES_PATH, params)
        if body is None:
            break
        records = extract_list(body)
        if not records:
            break
        machines.extend(records)
        total_pages, total = detect_pagination(body)
        print(f"  page {page}/{total_pages or '?'}  cumulative: {len(machines)}")
        if total_pages and page >= total_pages:
            break
        if len(records) < PAGE_SIZE:
            break
        time.sleep(SLEEP_SEC)
    print(f"  -> {len(machines)} 機種取得完了")
    return machines


def build_dataframe(machines: list[dict], borders: dict[int, dict]) -> pd.DataFrame:
    """機種リストとボーダーを結合して DataFrame を作る。"""
    rows = []
    for rec in machines:
        mid = rec.get("machine_id") or rec.get("id")
        border_rec = borders.get(int(mid)) if mid is not None else {}
        merged = {**rec, **(border_rec or {})}

        row: dict[str, Any] = {"machine_id": mid}
        for col, keys in KEY_MAP.items():
            row[col] = find_value(merged, keys)
        rows.append(row)

    df = pd.DataFrame(rows)
    return df


def main() -> None:
    # captures/_url_list.json があれば読み込んで候補を表示
    url_list_path = Path(__file__).parent / "captures" / "_url_list.json"
    if url_list_path.exists():
        urls = json.loads(url_list_path.read_text())
        print("=== step1_capture で記録された URL ===")
        for u in urls:
            print(f"  [{u['status']}] {u['url']}")
        print()

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        borders = scrape_borders(client)
        machines = scrape_machines(client)

    if not machines:
        print("\n機種データが取得できませんでした。")
        print("API_BASE / BORDERS_PATH / MACHINES_PATH を確認してください。")
        sys.exit(1)

    df = build_dataframe(machines, borders)
    print(f"\n[3] 結合結果: {len(df)} 行 × {len(df.columns)} 列")
    print(df[["機種名", "ボーダー", "初当たり期待出玉", "大当たり確率"]].head(10).to_string(index=False))

    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n-> {OUTPUT_CSV} に保存しました。")


if __name__ == "__main__":
    main()
