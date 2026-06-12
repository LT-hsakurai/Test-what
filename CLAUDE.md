@AGENTS.md

# 外観検査アプリ — プロジェクト引き継ぎ

## 概要

製品の外観をスマホカメラでリアルタイム検査するWebアプリ。
良品を登録しておくと、以降の製品をAIが自動でOK/NG判定し、異常箇所をヒートマップで表示する。

## アーキテクチャ

```
iPhone Safari
    │
    ▼
Next.js (Vercel)                    ← フロントエンド
  app/page.tsx                      ← メインUI（状態管理・カメラ・Canvas）
  app/api/explain/route.ts          ← Claude Haiku 呼び出し（NG時の説明文生成）
    │
    ▼ HTTP (FormData)
Python FastAPI (Railway)            ← バックエンド
  backend/main.py                   ← APIエンドポイント
  backend/inspector.py              ← PatchCore + テンプレートマッチング
```

## 技術スタック

| レイヤー | 技術 |
|---|---|
| フロントエンド | Next.js 16 (App Router) + TypeScript + Tailwind CSS v4 |
| バックエンド | Python FastAPI + Uvicorn |
| 異常検知モデル | PatchCore (ResNet18 バックボーン、CPU動作) |
| 位置合わせ | OpenCV テンプレートマッチング |
| AI説明文 | Claude Haiku (claude-haiku-4-5-20251001) |
| フロントデプロイ | Vercel |
| バックデプロイ | Railway (Dockerコンテナ) |

## ファイル構成

```
/
├── app/
│   ├── page.tsx              # メインUI（全画面・状態管理）
│   ├── layout.tsx            # ルートレイアウト
│   ├── globals.css           # Tailwind インポート
│   └── api/explain/route.ts  # Claude API ルート
├── backend/
│   ├── main.py               # FastAPI アプリ
│   ├── inspector.py          # PatchCore + マッチング
│   ├── requirements.txt      # Python 依存関係
│   ├── Dockerfile            # Railway デプロイ用
│   └── .env.example          # 環境変数サンプル
├── .env.example              # Vercel 環境変数サンプル
└── CLAUDE.md                 # このファイル
```

## 環境変数

### Vercel（フロントエンド）
```
NEXT_PUBLIC_BACKEND_URL=https://xxx.railway.app
ANTHROPIC_API_KEY=sk-ant-...
```

### Railway（バックエンド）
```
ANTHROPIC_API_KEY=sk-ant-...
```

## アプリの画面フロー

```
ホーム
  ├─ 良品を登録する
  │   ├─ ROI選択（タッチでマスク範囲指定）
  │   ├─ 3秒カウントダウン → 20フレーム自動撮影
  │   ├─ バックエンドで PatchCore 学習（+テンプレート保存）
  │   └─ 登録完了 → ホームへ
  └─ 検査を開始する（良品登録済みの場合のみ）
      ├─ リアルタイムカメラ映像
      ├─ 350ms ごとにフレーム送信 → ヒートマップ受信・描画
      ├─ マッチング ROI 枠表示（緑=自動位置合わせ / 黄=フォールバック）
      ├─ スコアバー + OK/NG バッジ
      ├─ 感度スライダー（0.5x〜2.0x）
      ├─ マッチング許容度スライダー（0.10〜0.90）
      └─ NG時「Claudeに欠陥を聞く」→ 欠陥詳細説明
```

## バックエンド API

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/health` | GET | 起動確認・モデル状態確認 |
| `/register` | POST | 良品登録（フルフレーム×20 + ROI座標） |
| `/inspect` | POST | 検査（フルフレーム + match_tolerance） |
| `/explain` | POST | Claude説明文生成（現在未使用、Vercel側で対応） |

### /register リクエスト
```
FormData:
  files: [JPEG, ...]   フルフレーム画像（最低5枚）
  roi_x, roi_y: float  ROI左上座標（0-1相対）
  roi_w, roi_h: float  ROI幅・高さ（0-1相対）
```

### /inspect レスポンス
```json
{
  "score": 0.123,
  "threshold": 0.456,
  "normalized_score": 0.27,
  "judgment": "OK",
  "heatmap": "<base64 PNG>",
  "match_confidence": 0.85,
  "match_roi": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}
}
```

## PatchCore の仕組み

1. **学習（良品登録）**: ResNet18の中間層（layer2+layer3）から特徴量を抽出し、パッチ特徴量バンクを構築。良品スコアの99パーセンタイル×1.25を閾値として保存。
2. **推論（検査）**: 検査フレームの特徴量と特徴量バンクの最近傍距離を計算 → 距離マップをヒートマップ化。
3. **位置合わせ**: OpenCV `matchTemplate` でフルフレーム内の製品位置を検出。信頼度が `match_threshold` 未満の場合は登録ROIにフォールバック。

## 注意事項・既知の制限

- Railway 無料枠は RAM 512MB のため、PyTorch読み込みでギリギリ。OOM が出る場合は Hobby プラン（$5/月）にアップグレード。
- テンプレートマッチングはスケール・回転変化に弱い。固定台での使用を前提とした設計。
- モデルは `backend/model_state.pkl` に保存される。Railway の再デプロイでは永続化されないため、デプロイのたびに良品再登録が必要（Volume マウントで解決可能）。
- iPhone Safari での動作を前提。カメラ使用には HTTPS 必須（Vercel/Railway は両方 HTTPS）。

## 今後の改善案

- [ ] マルチ製品対応（複数の良品モデルを切り替え）
- [ ] 検査履歴の保存・一覧表示
- [ ] スケール・回転に対応した特徴点マッチング（ORB/SIFT）
- [ ] WideResNet50 バックボーンへの切り替えオプション（高精度化）
- [ ] 検査結果のCSVエクスポート
- [ ] Railway Volume でモデルを永続化
