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

IMG_SIZE = 224
SAVE_PATH = pathlib.Path("model_state.pkl")


class PatchCoreInspector:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.feature_bank: torch.Tensor | None = None
        self.threshold: float | None = None
        self.is_fitted = False

        self.transform = T.Compose([
            T.Resize((IMG_SIZE, IMG_SIZE)),
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
            pickle.dump({"bank": self.feature_bank.cpu(), "threshold": self.threshold}, f)

    def _load(self):
        if SAVE_PATH.exists():
            try:
                with open(SAVE_PATH, "rb") as f:
                    s = pickle.load(f)
                self.feature_bank = s["bank"].to(self.device)
                self.threshold = s["threshold"]
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
        if bank.shape[0] > 10_000:
            idx = torch.randperm(bank.shape[0])[:10_000]
            bank = bank[idx]

        self.feature_bank = bank
        self.is_fitted = True

        # 閾値計算は抽出済み特徴量を再利用（再抽出すると学習時間が2倍になる）
        scores = []
        for patches in patches_list:
            dist = torch.cdist(patches, bank)
            scores.append(float(dist.min(dim=1).values.max()))
        self.threshold = float(np.percentile(scores, 99)) * 1.25
        self._save()

        return {
            "bank_size": int(bank.shape[0]),
            "threshold": round(self.threshold, 4),
            "fit_seconds": round(time.time() - t0, 1),
        }

    def _score(self, img_bytes: bytes) -> float:
        tensor = self._preprocess(img_bytes)
        feats = self._extract(tensor)
        patches = self._to_patches(feats)
        dist = torch.cdist(patches, self.feature_bank)
        return float(dist.min(dim=1).values.max())

    def predict(self, img_bytes: bytes, heat_threshold: float = 0.5) -> dict:
        if not self.is_fitted:
            raise RuntimeError("良品が未登録です")

        tensor = self._preprocess(img_bytes)
        feats = self._extract(tensor)
        B, C, h, w = feats.shape
        patches = self._to_patches(feats)

        dist = torch.cdist(patches, self.feature_bank)
        anomaly_map = dist.min(dim=1).values.reshape(h, w).cpu().float().numpy()

        score = float(anomaly_map.max())
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

        rgba = cv2.resize(rgba, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_LINEAR)
        _, buf = cv2.imencode(".png", rgba)
        return base64.b64encode(buf.tobytes()).decode()
