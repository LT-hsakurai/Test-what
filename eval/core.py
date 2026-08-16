"""パラメータ化した PatchCore — 検証用。

backend/inspector.py の挙動を Config の既定値でそのまま再現しつつ、
疑わしい判断（ぼかし・スコア関数・解像度・バンク間引き・ROI）を
1つずつ差し替えられるようにしたもの。

本番実装ではなく、あくまで「どの判断が偽NGを生んでいたか」を測るための道具。
"""

from __future__ import annotations

import io
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F
import torchvision.models as models
import torchvision.transforms as T
from PIL import Image

from .config import Config


class ParamPatchCore:
    def __init__(self, cfg: Config, device: str | None = None):
        self.cfg = cfg
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.transform = T.Compose([
            T.Resize((cfg.img_h, cfg.img_w)),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

        if cfg.backbone == "resnet18":
            backbone = models.resnet18(weights="DEFAULT")
        else:
            backbone = models.wide_resnet50_2(weights="DEFAULT")
        backbone.eval().to(self.device)

        self._f2: torch.Tensor | None = None
        self._f3: torch.Tensor | None = None
        backbone.layer2.register_forward_hook(lambda m, i, o: setattr(self, "_f2", o))
        backbone.layer3.register_forward_hook(lambda m, i, o: setattr(self, "_f3", o))
        self.backbone = backbone

        self.feature_bank: torch.Tensor | None = None
        self.threshold: float | None = None
        self.grid: tuple[int, int] | None = None

    # ------------------------------------------------------------ 前処理 --
    def _preprocess(self, data: bytes) -> torch.Tensor:
        img = Image.open(io.BytesIO(data)).convert("RGB")

        # V6: ROI で検査対象だけを切り出す。背景・机・手を学習させない。
        if self.cfg.roi is not None:
            x, y, w, h = self.cfg.roi
            W, H = img.size
            img = img.crop((
                int(x * W), int(y * H),
                int((x + w) * W), int((y + h) * H),
            ))

        return self.transform(img).unsqueeze(0).to(self.device)

    @torch.no_grad()
    def _extract(self, tensor: torch.Tensor) -> torch.Tensor:
        self.backbone(tensor)
        l2 = self._f2
        l3 = F.interpolate(self._f3, size=l2.shape[-2:], mode="bilinear", align_corners=False)
        return torch.cat([l2, l3], dim=1)

    def _to_patches(self, feats: torch.Tensor) -> torch.Tensor:
        # PatchCore 本来の 3x3 近傍 average pooling。現行プロトタイプは未実装で、
        # そのぶんノイズに敏感になっている。
        if self.cfg.patch_pool:
            feats = F.avg_pool2d(feats, kernel_size=3, stride=1, padding=1)
        _, C, h, w = feats.shape
        self.grid = (h, w)
        return feats[0].permute(1, 2, 0).reshape(-1, C)

    # -------------------------------------------------------------- バンク --
    def _subsample(self, bank: torch.Tensor) -> torch.Tensor:
        strategy, size = self.cfg.bank_strategy, self.cfg.bank_size
        if strategy == "all" or bank.shape[0] <= size:
            return bank
        if strategy == "random":
            # 現行。一様間引きは「希少だが正常」なパッチを優先的に落とす。
            idx = torch.randperm(bank.shape[0], device=bank.device)[:size]
            return bank[idx]
        return self._greedy_coreset(bank, size)

    @torch.no_grad()
    def _greedy_coreset(self, bank: torch.Tensor, size: int) -> torch.Tensor:
        """greedy k-center。ランダム間引きと逆に、希少なパッチを優先して残す。"""
        n = bank.shape[0]
        selected = torch.zeros(size, dtype=torch.long, device=bank.device)
        start = int(torch.randint(n, (1,)).item())
        selected[0] = start
        min_dist = torch.cdist(bank, bank[start:start + 1]).squeeze(1)

        for i in range(1, size):
            nxt = int(min_dist.argmax().item())
            selected[i] = nxt
            d = torch.cdist(bank, bank[nxt:nxt + 1]).squeeze(1)
            min_dist = torch.minimum(min_dist, d)

        return bank[selected]

    # ------------------------------------------------------- 異常マップ --
    def _anomaly_map(self, patches: torch.Tensor, bank: torch.Tensor) -> np.ndarray:
        h, w = self.grid
        dist = torch.cdist(patches, bank)
        amap = dist.min(dim=1).values.reshape(h, w).cpu().float().numpy()

        # V1: 現行は sigma=4.0。18x32 のマップに 33x33 のカーネルが掛かり、
        # 単一セルの欠陥はピークが 1/101 に希釈される。
        if self.cfg.smooth_sigma > 0:
            amap = cv2.GaussianBlur(amap, (0, 0), self.cfg.smooth_sigma)
        return amap

    def _map_score(self, amap: np.ndarray) -> float:
        # V2: p99 は 576セルの上位5.76セル目。約6セル未満の欠陥は
        # 定義上スコアを動かせない。
        fn = self.cfg.score_fn
        if fn == "p99":
            return float(np.percentile(amap, 99))
        if fn == "max":
            return float(amap.max())
        k = min(self.cfg.topk, amap.size)
        return float(np.sort(amap.ravel())[-k:].mean())

    # ---------------------------------------------------------------- 学習 --
    def fit(self, images: list[bytes]) -> float:
        t0 = time.time()

        patches_list = [self._to_patches(self._extract(self._preprocess(b))) for b in images]
        full_bank = torch.cat(patches_list, dim=0)
        self.feature_bank = self._subsample(full_bank)

        # 閾値は leave-one-out で算出する。自分自身を含むバンクと比較すると
        # 最近傍距離が ≈0 になり閾値が潰れる（07af491 で修正済みの罠）。
        scores = []
        for i, patches in enumerate(patches_list):
            others = torch.cat([p for j, p in enumerate(patches_list) if j != i], dim=0)
            # 現行は校正時だけ間引きをせず、推論時は3000に間引く。バンクが疎な
            # ほど最近傍距離は大きく出るので、推論スコアは常に偽NG側へ寄る。
            if self.cfg.consistent_calibration_bank:
                others = self._subsample(others)
            scores.append(self._map_score(self._anomaly_map(patches, others)))

        self.threshold = self._decide_threshold(np.asarray(scores, dtype=np.float64))
        return time.time() - t0

    def _decide_threshold(self, scores: np.ndarray) -> float:
        p = self.cfg.threshold_policy
        if p == "p99x1.25":
            # 現行。10要素の p99 は補間で実質最大値なので max*1.25 と同義。
            return max(float(np.percentile(scores, 99)) * 1.25, 1e-6)
        if p == "mean_k_std":
            return max(float(scores.mean() + self.cfg.threshold_k * scores.std()), 1e-6)
        # 許容偽NG率から分位点で決める
        q = 100.0 * (1.0 - self.cfg.target_fpr)
        return max(float(np.percentile(scores, q)), 1e-6)

    # ---------------------------------------------------------------- 推論 --
    def predict(self, img_bytes: bytes) -> tuple[float, float]:
        """(スコア, 推論ミリ秒) を返す。"""
        t0 = time.time()
        patches = self._to_patches(self._extract(self._preprocess(img_bytes)))
        score = self._map_score(self._anomaly_map(patches, self.feature_bank))
        return score, (time.time() - t0) * 1000.0
