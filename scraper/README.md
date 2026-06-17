# DMM ぱちタウン スクレイパー

## セットアップ

```bash
cd scraper
pip install -r requirements.txt
playwright install chromium
```

## 実行手順

### Step 1–3: エンドポイント探索（Playwright）

```bash
python step1_capture.py
```

`captures/` に JSON ファイルが保存され、URL 一覧が表示されます。  
結果を確認して `step4_scraper.py` の以下の定数を修正してください。

```python
API_BASE      = "https://p-town.dmm.com"
BORDERS_PATH  = "/api/v1/machine_borders"   # 実際のパスに修正
MACHINES_PATH = "/api/v1/machines"          # 実際のパスに修正
KEY_MAP       = { ... }                     # 実際のキー名に修正
```

### Step 4–5: 全件取得 → CSV 出力（httpx）

```bash
python step4_scraper.py
```

`machines.csv` が生成されます。

## 出力列

| 列名 | 説明 |
|------|------|
| machine_id | 機種ID |
| 機種名 | 台名 |
| ボーダー | ボーダー (玉/時) |
| 初当たり期待出玉 | 初当たり時の期待出玉数 |
| 大当たり確率 | 大当たり確率 (例: 1/319) |
