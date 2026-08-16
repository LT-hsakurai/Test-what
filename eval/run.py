"""検証ランナー — V1〜V6 を回して比較表を出す。

    python -m eval.run data/myproduct
    python -m eval.run data/myproduct --roi 0.25,0.20,0.50,0.60
    python -m eval.run data/myproduct --only baseline,V1b,V6b

データ配置（撮影手順は eval/README.md を参照）:

    data/myproduct/
      train/    良品。登録に使う。置き直しながら10〜20回撮る
      good/     良品。評価用。train には入れない（hold-out）
      ng/       既知の不良。最低3枚

判定の良し悪しは train ではなく good / ng で測る。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np

from .config import Config, verification_suite
from .core import ParamPatchCore
from .metrics import Result, format_table, write_csv

SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_dir(path: pathlib.Path) -> list[bytes]:
    if not path.is_dir():
        return []
    files = sorted(p for p in path.iterdir() if p.suffix.lower() in SUFFIXES)
    return [p.read_bytes() for p in files]


def run_one(cfg: Config, train: list[bytes], good: list[bytes], ng: list[bytes]) -> Result:
    model = ParamPatchCore(cfg)
    fit_seconds = model.fit(train)

    good_scores, ms = [], []
    for b in good:
        s, t = model.predict(b)
        good_scores.append(s)
        ms.append(t)
    ng_scores = []
    for b in ng:
        s, t = model.predict(b)
        ng_scores.append(s)
        ms.append(t)

    return Result(
        config_name=cfg.name,
        threshold=model.threshold,
        good_scores=np.asarray(good_scores, dtype=np.float64),
        ng_scores=np.asarray(ng_scores, dtype=np.float64),
        fit_seconds=fit_seconds,
        predict_ms=float(np.mean(ms)) if ms else float("nan"),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="外観検査アルゴリズムの検証ランナー")
    ap.add_argument("dataset", type=pathlib.Path, help="train/ good/ ng/ を含むディレクトリ")
    ap.add_argument("--roi", type=str, default=None,
                    help="検査対象の矩形を相対座標で x,y,w,h（V6 用）")
    ap.add_argument("--only", type=str, default=None,
                    help="実行する設定名をカンマ区切りで指定（前方一致）")
    ap.add_argument("--csv", type=pathlib.Path, default=None, help="結果のCSV出力先")
    ap.add_argument("--seed", type=int, default=0, help="乱数シード（間引きの再現性）")
    args = ap.parse_args(argv)

    import torch
    torch.manual_seed(args.seed)

    train = load_dir(args.dataset / "train")
    good = load_dir(args.dataset / "good")
    ng = load_dir(args.dataset / "ng")

    if len(train) < 5:
        print(f"error: train/ の画像が {len(train)} 枚しかありません（最低5枚）", file=sys.stderr)
        return 1
    if not good and not ng:
        print("error: good/ と ng/ の両方が空です。評価できません", file=sys.stderr)
        return 1
    if not ng:
        print("warning: ng/ が空です。見逃し率と分離マージンは測れません。\n"
              "         既知の不良を最低3枚撮ってください — これが無いまま\n"
              "         実運用に出したことがプロトタイプ最大の失敗でした。\n",
              file=sys.stderr)

    roi = None
    if args.roi:
        parts = [float(v) for v in args.roi.split(",")]
        if len(parts) != 4:
            print("error: --roi は x,y,w,h の4つの数値で指定してください", file=sys.stderr)
            return 1
        roi = (parts[0], parts[1], parts[2], parts[3])

    configs = verification_suite(roi)
    if args.only:
        wanted = [w.strip() for w in args.only.split(",")]
        configs = [c for c in configs if any(c.name.startswith(w) for w in wanted)]
        if not configs:
            print("error: --only にマッチする設定がありません", file=sys.stderr)
            return 1

    print(f"データ: train={len(train)}  good={len(good)}  ng={len(ng)}")
    if roi is None:
        print("ROI: 未指定（V6 はスキップされます。--roi で指定してください）")
    print()

    results: list[Result] = []
    for cfg in configs:
        print(f"  実行中: {cfg.name} ...", end="", flush=True)
        torch.manual_seed(args.seed)  # 間引きの再現性を確保
        try:
            r = run_one(cfg, train, good, ng)
        except Exception as e:  # noqa: BLE001 - 1つ失敗しても残りは回す
            print(f" 失敗: {type(e).__name__}: {e}")
            continue
        results.append(r)
        print(f" AUROC={r.auroc:.4f}  偽NG={r.false_ng_rate * 100:.1f}%")

    if not results:
        print("\n実行できた設定がありません", file=sys.stderr)
        return 1

    print()
    print(format_table(results))
    print()
    print("読み方:")
    print("  偽NG率      良品を誤ってNGにした割合。現場の信用を最も損なう")
    print("  分離マージン 正なら良品とNGが完全分離。負ならどんな閾値でも破綻する")
    print("  良品CV      良品スコアのばらつき。大きいまま閾値を締めると必ず偽NGが出る")
    print()
    print("baseline と V1b/V6a を比べれば、「アルゴリズムの問題か撮影条件の問題か」が決まります。")

    if args.csv:
        write_csv(results, str(args.csv))
        print(f"\nCSV を書き出しました: {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
