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

        # ResNet18: fast CPU inference (~50ms/frame)
        backbone = models.resnet18(weights="DEFAULT")
        backbone.eval().to(self.device)
        self._f2: torch.Tensor | None = None
        self._f3: torch.Tensor | None = None
        backbone.layer2.register_forward_hook(lambda m, i, o: setattr(self, "_f2", o))
        backbone.layer3.register_forward_hook(lambda m, i, o: setattr(self, "_f3", o))
        self.backbone = backbone

        self._load()

    # ------------------------------------------------------------------ #

    def _load(self):
        if SAVE_PATH.exists():
            with open(SAVE_PATH, "rb") as f:
                state = pickle.load(f)
            self.feature_bank = state["bank"].to(self.device)
            self.threshold = state["threshold"]
            self.is_fitted = True

    def _save(self):
        with open(SAVE_PATH, "wb") as f:
            pickle.dump({"bank": self.feature_bank.cpu(), "threshold": self.threshold}, f)

    # ------------------------------------------------------------------ #

    def _preprocess(self, data: bytes) -> torch.Tensor:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        return self.transform(img).unsqueeze(0).to(self.device)

    @torch.no_grad()
    def _extract(self, tensor: torch.Tensor) -> torch.Tensor:
        self.backbone(tensor)
        l2 = self._f2                                                        # (1,128,28,28)
        l3 = F.interpolate(self._f3, size=l2.shape[-2:],                    # (1,256,28,28)
                           mode="bilinear", align_corners=False)
        return torch.cat([l2, l3], dim=1)                                    # (1,384,28,28)

    def _to_patches(self, feats: torch.Tensor) -> torch.Tensor:
        B, C, h, w = feats.shape
        return feats[0].permute(1, 2, 0).reshape(-1, C)                      # (h*w, C)

    # ------------------------------------------------------------------ #

    def fit(self, images: list[bytes]) -> dict:
        patches_list = []
        for img_bytes in images:
            feats = self._extract(self._preprocess(img_bytes))
            patches_list.append(self._to_patches(feats))

        bank = torch.cat(patches_list, dim=0)
        if bank.shape[0] > 10_000:
            idx = torch.randperm(bank.shape[0])[:10_000]
            bank = bank[idx]

        self.feature_bank = bank
        self.is_fitted = True

        # Calibrate threshold from good images
        scores = [self._max_score(img_bytes) for img_bytes in images]
        self.threshold = float(np.percentile(scores, 99)) * 1.25

        self._save()
        return {"bank_size": int(bank.shape[0]), "threshold": round(self.threshold, 4)}

    def _max_score(self, img_bytes: bytes) -> float:
        feats = self._extract(self._preprocess(img_bytes))
        patches = self._to_patches(feats)
        dist = torch.cdist(patches, self.feature_bank)
        return float(dist.min(dim=1).values.max())

    # ------------------------------------------------------------------ #

    def predict(self, img_bytes: bytes) -> dict:
        if not self.is_fitted:
            raise RuntimeError("良品が未登録です")

        feats = self._extract(self._preprocess(img_bytes))
        B, C, h, w = feats.shape
        patches = self._to_patches(feats)

        dist = torch.cdist(patches, self.feature_bank)               # (h*w, N_bank)
        anomaly_map = dist.min(dim=1).values.reshape(h, w).cpu().float().numpy()

        score = float(anomaly_map.max())
        normalized = score / self.threshold
        judgment = "NG" if normalized > 1.0 else "OK"
        heatmap = self._colorize(anomaly_map, normalized)

        return {
            "score": round(score, 4),
            "threshold": round(self.threshold, 4),
            "normalized_score": round(normalized, 3),
            "judgment": judgment,
            "heatmap": heatmap,
        }

    def _colorize(self, anomaly_map: np.ndarray, normalized_score: float) -> str:
        am = anomaly_map.astype(np.float32)
        if am.max() > am.min():
            am_n = (am - am.min()) / (am.max() - am.min())
        else:
            am_n = np.zeros_like(am)

        am_u8 = (am_n * 255).astype(np.uint8)
        bgr = cv2.applyColorMap(am_u8, cv2.COLORMAP_JET)
        rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)

        # Low-anomaly regions → transparent
        alpha = np.clip((am_n - 0.2) * (255 / 0.8), 0, 200).astype(np.uint8)
        rgba[:, :, 3] = alpha

        rgba = cv2.resize(rgba, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_LINEAR)
        _, buf = cv2.imencode(".png", rgba)
        return base64.b64encode(buf.tobytes()).decode()
