import torch
import torch.nn.functional as F
import torchvision.models as models
import torchvision.transforms as T
import numpy as np
from PIL import Image
import io
import base64
import cv2
import pickle
import pathlib

IMG_W, IMG_H = 256, 144  # 16:9 を維持して歪みを防ぐ（縦横を32の倍数に）
BANK_SIZE = 3000         # 特徴量バンク上限（小さいほど検査が速い）
SMOOTH_SIGMA = 4.0       # 異常マップのガウシアンぼかし
SAVE_PATH = pathlib.Path("model_state.pkl")


class PatchCoreInspector:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.feature_bank: torch.Tensor | None = None
        self.threshold: float | None = None
        self.is_fitted = False
        self.reference_image: bytes | None = None

        self.transform = T.Compose([
            T.Resize((IMG_H, IMG_W)),  # アスペクト比を保って 16:9 にリサイズ
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

        backbone = models.resnet18(weights="DEFAULT")
        backbone.eval().to(self.device)
        self._f2: torch.Tensor | None = None
        self._f3: torch.Tensor | None = None
        backbone.layer2.register_forward_hook(lambda m, i, o: setattr(self, "_f2", o))
        backbone.layer3.register_forward_hook(lambda m, i, o: setattr(self, "_f3", o))
        self.backbone = backbone

        self._load()

    def _save(self):
        with open(SAVE_PATH, "wb") as f:
            pickle.dump({
                "bank": self.feature_bank.cpu(),
                "threshold": self.threshold,
                "reference_image": self.reference_image,
            }, f)

    def _load(self):
        if SAVE_PATH.exists():
            try:
                with open(SAVE_PATH, "rb") as f:
                    s = pickle.load(f)
                self.feature_bank = s["bank"].to(self.device)
                self.threshold = s["threshold"]
                self.reference_image = s.get("reference_image", None)
                self.is_fitted = True
            except Exception:
                pass  # 古い形式のファイルは無視

    @torch.no_grad()
    def _extract(self, tensor: torch.Tensor) -> torch.Tensor:
        self.backbone(tensor)
        l2 = self._f2
        l3 = F.interpolate(self._f3, size=l2.shape[-2:], mode="bilinear", align_corners=False)
        return torch.cat([l2, l3], dim=1)

    def _preprocess(self, data: bytes) -> torch.Tensor:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        return self.transform(img).unsqueeze(0).to(self.device)

    def _to_patches(self, feats: torch.Tensor) -> torch.Tensor:
        B, C, h, w = feats.shape
        return feats[0].permute(1, 2, 0).reshape(-1, C)

    def fit(self, images: list[bytes]) -> dict:
        import time
        t0 = time.time()

        patches_list = []
        for img_bytes in images:
            tensor = self._preprocess(img_bytes)
            feats = self._extract(tensor)
            patches_list.append(self._to_patches(feats))

        bank = torch.cat(patches_list, dim=0)
        if bank.shape[0] > BANK_SIZE:
            idx = torch.randperm(bank.shape[0])[:BANK_SIZE]
            bank = bank[idx]

        self.feature_bank = bank
        self.is_fitted = True
        self.reference_image = images[len(images) // 2]  # 中央フレームを良品参照として保存

        # 閾値は leave-one-out で計算: 各フレームを「自分以外のフレームのパッチ」
        # と比較する。自分自身を含むバンクと比較すると距離が常にほぼ0になり、
        # 閾値が極小化して全フレームがNG判定になってしまう。
        scores = []
        for i, patches in enumerate(patches_list):
            others = torch.cat([p for j, p in enumerate(patches_list) if j != i], dim=0)
            amap = self._anomaly_map(patches, others)
            scores.append(self._map_score(amap))
        self.threshold = max(float(np.percentile(scores, 99)) * 1.25, 1e-6)
        self._save()

        return {
            "bank_size": int(bank.shape[0]),
            "threshold": round(self.threshold, 4),
            "fit_seconds": round(time.time() - t0, 1),
        }

    def _patch_grid(self, n_patches: int) -> tuple[int, int]:
        # layer2 の特徴マップ形状（入力解像度から決まる）
        return IMG_H // 8, IMG_W // 8

    def _anomaly_map(self, patches: torch.Tensor, bank: torch.Tensor) -> np.ndarray:
        h, w = self._patch_grid(patches.shape[0])
        dist = torch.cdist(patches, bank)
        amap = dist.min(dim=1).values.reshape(h, w).cpu().float().numpy()
        # ガウシアンぼかしでノイズ除去 → スコア安定＆ヒートマップ平滑化
        return cv2.GaussianBlur(amap, (0, 0), SMOOTH_SIGMA)

    def _map_score(self, amap: np.ndarray) -> float:
        # 最大1点ではなく上位パーセンタイルで安定化（外れ値に強い）
        return float(np.percentile(amap, 99))

    def predict(self, img_bytes: bytes, heat_threshold: float = 0.5) -> dict:
        if not self.is_fitted:
            raise RuntimeError("良品が未登録です")

        tensor = self._preprocess(img_bytes)
        feats = self._extract(tensor)
        patches = self._to_patches(feats)
        anomaly_map = self._anomaly_map(patches, self.feature_bank)

        score = self._map_score(anomaly_map)
        normalized = score / self.threshold
        judgment = "NG" if normalized > 1.0 else "OK"

        return {
            "score": round(score, 4),
            "threshold": round(self.threshold, 4),
            "normalized_score": round(normalized, 3),
            "judgment": judgment,
            "heatmap": self._colorize(anomaly_map, heat_threshold),
        }

    def _colorize(self, anomaly_map: np.ndarray, cutoff: float = 0.5) -> str:
        # 学習した閾値を基準に正規化（1.0 = NG境界）。フレームごとの min-max では
        # なく絶対基準なので、良品フレームでは赤が出ない。
        thr = self.threshold if self.threshold and self.threshold > 0 else float(anomaly_map.max() + 1e-9)
        rel = anomaly_map.astype(np.float32) / thr

        # 色（重症度）: 0〜1.5倍を JET にマッピング
        severity = np.clip(rel / 1.5, 0, 1)
        am_u8 = (severity * 255).astype(np.uint8)
        bgr = cv2.applyColorMap(am_u8, cv2.COLORMAP_JET)
        rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)

        # 透明度: cutoff 未満は透明、そこから 0.6倍ぶんでフェードイン
        visibility = np.clip((rel - cutoff) / 0.6, 0, 1)
        rgba[:, :, 3] = (visibility * 200).astype(np.uint8)

        # 16:9 のまま高解像度に拡大（映像にそのまま重なる）
        rgba = cv2.resize(rgba, (IMG_W * 4, IMG_H * 4), interpolation=cv2.INTER_LINEAR)
        _, buf = cv2.imencode(".png", rgba)
        return base64.b64encode(buf.tobytes()).decode()

