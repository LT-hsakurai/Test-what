"""評価指標 — 「精度が上がった」を数字で言えるようにするための最小セット。

プロトタイプにはこれが一切なく、閾値崩壊バグ（異常度61870%）が実機で
発覚するまで気づかれなかった。sklearn には依存しない（numpy のみ）。
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class Result:
    config_name: str
    threshold: float
    good_scores: np.ndarray
    ng_scores: np.ndarray
    fit_seconds: float
    predict_ms: float

    # ------------------------------------------------------------ 判定指標 --
    @property
    def false_ng_rate(self) -> float:
        """偽NG率 — 良品を誤ってNGにした割合。現場の信用を最も損なう指標。"""
        if self.good_scores.size == 0:
            return float("nan")
        return float((self.good_scores > self.threshold).mean())

    @property
    def miss_rate(self) -> float:
        """見逃し率 — 不良を OK と判定した割合。"""
        if self.ng_scores.size == 0:
            return float("nan")
        return float((self.ng_scores <= self.threshold).mean())

    @property
    def auroc(self) -> float:
        """画像単位 AUROC。閾値の決め方に依存しないので、手法そのものの
        分離能力を比べるのに使う。順位ベースで計算（同値は平均順位）。"""
        g, n = self.good_scores, self.ng_scores
        if g.size == 0 or n.size == 0:
            return float("nan")
        allv = np.concatenate([g, n])
        order = allv.argsort()
        ranks = np.empty(allv.size, dtype=np.float64)
        ranks[order] = np.arange(1, allv.size + 1)
        # 同値の平均順位
        _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
        sums = np.zeros(cnt.size)
        np.add.at(sums, inv, ranks)
        ranks = (sums / cnt)[inv]
        rank_ng = ranks[g.size:].sum()
        return float((rank_ng - n.size * (n.size + 1) / 2) / (g.size * n.size))

    @property
    def margin(self) -> float:
        """分離マージン — (NG最小 - 良品最大) / 良品の標準偏差。

        正なら良品とNGが完全に分離している。負なら重なっており、
        どんな閾値を選んでも偽NGか見逃しのどちらかが出る。
        「このモデルは使えません」と正直に言うための指標。
        """
        g, n = self.good_scores, self.ng_scores
        if g.size == 0 or n.size == 0:
            return float("nan")
        sd = float(g.std())
        if sd <= 0:
            return float("inf") if n.min() > g.max() else float("-inf")
        return float((n.min() - g.max()) / sd)

    @property
    def good_cv(self) -> float:
        """良品スコアの変動係数 — 撮影条件がどれだけ揺れているかの代理指標。
        これが大きいまま閾値を締めると、必ず偽NGが出る。"""
        m = float(self.good_scores.mean())
        return float(self.good_scores.std() / m) if m > 0 else float("nan")

    def row(self) -> dict:
        return {
            "config": self.config_name,
            "AUROC": self.auroc,
            "偽NG率": self.false_ng_rate,
            "見逃し率": self.miss_rate,
            "分離マージン": self.margin,
            "良品CV": self.good_cv,
            "閾値": self.threshold,
            "学習秒": self.fit_seconds,
            "推論ms": self.predict_ms,
        }


def format_table(results: list[Result]) -> str:
    """比較表を端末幅で読める形に整形する。"""
    rows = [r.row() for r in results]
    if not rows:
        return "(結果なし)"

    headers = list(rows[0].keys())

    def fmt(k: str, v) -> str:
        if isinstance(v, str):
            return v
        if v != v:  # NaN
            return "-"
        if k in ("偽NG率", "見逃し率"):
            return f"{v * 100:.1f}%"
        if k in ("AUROC",):
            return f"{v:.4f}"
        if k in ("分離マージン", "良品CV"):
            return f"{v:+.2f}"
        if k == "閾値":
            return f"{v:.4f}"
        if k == "学習秒":
            return f"{v:.1f}"
        if k == "推論ms":
            return f"{v:.1f}"
        return str(v)

    cells = [[fmt(k, r[k]) for k in headers] for r in rows]

    def width(s: str) -> int:
        # 全角を2幅として数える
        return sum(2 if ord(c) > 0x2E80 else 1 for c in s)

    widths = [
        max(width(h), max(width(c[i]) for c in cells)) for i, h in enumerate(headers)
    ]

    def pad(s: str, w: int) -> str:
        return s + " " * (w - width(s))

    out = ["  ".join(pad(h, widths[i]) for i, h in enumerate(headers))]
    out.append("  ".join("-" * w for w in widths))
    for c in cells:
        out.append("  ".join(pad(c[i], widths[i]) for i in range(len(headers))))
    return "\n".join(out)


def write_csv(results: list[Result], path: str) -> None:
    import csv

    rows = [r.row() for r in results]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
