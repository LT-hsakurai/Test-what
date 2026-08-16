"""検証設定 — V1〜V6 の各ノブをここに集約する。

現行プロトタイプ（backend/inspector.py）の挙動を `Config()` の既定値で
そのまま再現できるようにしてある。各フィールドを振ることで、
「どの判断が偽NGを生んでいたのか」を1つずつ切り分ける。
"""

from dataclasses import dataclass, field, asdict
from typing import Literal


@dataclass(frozen=True)
class Config:
    name: str = "baseline"

    # --- V3: 入力解像度 ---------------------------------------------------
    # 現行は 256x144。1特徴セル = 入力8x8px なので、検出したい最小欠陥が
    # 1セルに満たないと原理的に検出できない。
    img_h: int = 144
    img_w: int = 256

    # --- V6: ROI（背景を学習させない） -----------------------------------
    # (x, y, w, h) を 0-1 の相対座標で指定。None ならフルフレーム（現行）。
    roi: tuple[float, float, float, float] | None = None

    # --- V1: 異常マップのぼかし ------------------------------------------
    # 現行は 4.0。18x32 のマップに対して cv2 が決めるカーネルは 33x33 で、
    # マップの高さを超える。単一セルの突起はピークが 1/101 に希釈される。
    smooth_sigma: float = 4.0

    # --- V2: スコア関数 ---------------------------------------------------
    # 'p99'  : 現行。576セルの p99 = 上位5.76セル目。小面積の欠陥は寄与しない
    # 'max'  : 最大値。1セルの欠陥でも拾えるがノイズに弱い
    # 'topk' : 上位k個の平均。k は検出したい最小欠陥が占めるセル数から決める
    score_fn: Literal["p99", "max", "topk"] = "p99"
    topk: int = 3

    # --- V5: 特徴量バンク -------------------------------------------------
    # 'random'  : 現行。torch.randperm で一様間引き。希少だが正常なパッチを
    #             優先的に捨てるため、偽NGホットスポットが構造的に生じる
    # 'all'     : 間引かない
    # 'coreset' : greedy k-center（PatchCore 本来の手法）。希少パッチを残す
    bank_strategy: Literal["random", "all", "coreset"] = "random"
    bank_size: int = 3000

    # 現行は校正バンク（LOO・間引きなし 5184）と推論バンク（3000）が
    # 食い違っており、推論スコアが系統的に大きく出る＝常に偽NG側へバイアス。
    # True にすると校正時も推論と同じ間引きを適用して条件を揃える。
    consistent_calibration_bank: bool = False

    # PatchCore 本来の 3x3 近傍 average pooling。現行は未実装。
    patch_pool: bool = False

    # --- バックボーン -----------------------------------------------------
    backbone: Literal["resnet18", "wide_resnet50_2"] = "resnet18"

    # --- 閾値の決め方 -----------------------------------------------------
    # 'p99x1.25'   : 現行。10サンプルの p99 は補間により実質 max なので
    #                `max * 1.25` とほぼ同義。統計的な裏づけはない
    # 'mean_k_std' : 良品スコアの平均 + k*標準偏差
    # 'fpr_target' : 良品の許容誤検出率（例 1%）から分位点で決める
    threshold_policy: Literal["p99x1.25", "mean_k_std", "fpr_target"] = "p99x1.25"
    threshold_k: float = 3.0
    target_fpr: float = 0.01

    def describe(self) -> str:
        return ", ".join(
            f"{k}={v}" for k, v in asdict(self).items() if k != "name"
        )


# ---------------------------------------------------------------- 検証セット --
# V1〜V6。それぞれ baseline から1軸だけ動かし、効果を単独で測る。

def verification_suite(roi: tuple[float, float, float, float] | None) -> list[Config]:
    """設計書の V1〜V6 に対応する設定群を返す。

    roi には手動で切った検査対象の矩形を渡す（V6 で使用）。
    """
    suite = [
        Config(name="baseline (現行の再現)"),

        # V1 — ぼかしを外す
        Config(name="V1a sigma=1.0", smooth_sigma=1.0),
        Config(name="V1b sigma=0.0", smooth_sigma=0.0),

        # V2 — スコア関数
        Config(name="V2a score=max", score_fn="max"),
        Config(name="V2b score=top3", score_fn="topk", topk=3),

        # V3 — 解像度
        Config(name="V3  512x288", img_h=288, img_w=512),

        # V5 — バンク（V4 は撮影方法の比較なのでデータ側で分ける）
        Config(name="V5a bank=all",     bank_strategy="all", consistent_calibration_bank=True),
        Config(name="V5b bank=coreset", bank_strategy="coreset", consistent_calibration_bank=True),
        Config(name="V5c 校正/推論を揃える", consistent_calibration_bank=True),
    ]

    if roi is not None:
        # V6 — ROI で背景を捨てる
        suite += [
            Config(name="V6a ROI のみ", roi=roi),
            # 最有力の組み合わせ: ROI + ぼかし除去 + max スコア + coreset
            Config(
                name="V6b ROI+σ0+max+coreset",
                roi=roi,
                smooth_sigma=0.0,
                score_fn="topk",
                topk=3,
                bank_strategy="coreset",
                consistent_calibration_bank=True,
                patch_pool=True,
            ),
        ]

    return suite
