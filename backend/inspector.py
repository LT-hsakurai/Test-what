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
MATCH_THRESHOLD = 0.35   # template matching confidence floor


class PatchCoreInspector:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.feature_bank: torch.Tensor | None = None
        self.threshold: float | None = None
        self.reference_template: np.ndarray | None = None  # BGR crop
        self.registered_roi: tuple[float, float, float, float] | None = None
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

    # ---------------------------------------------------------------- persist --

    def _save(self):
        with open(SAVE_PATH, "wb") as f:
            pickle.dump({
                "bank": self.feature_bank.cpu(),
                "threshold": self.threshold,
                "template": self.reference_template,
                "roi": self.registered_roi,
            }, f)

    def _load(self):
        if SAVE_PATH.exists():
            with open(SAVE_PATH, "rb") as f:
                s = pickle.load(f)
            self.feature_bank = s["bank"].to(self.device)
            self.threshold = s["threshold"]
            self.reference_template = s.get("template")
            self.registered_roi = s.get("roi")
            self.is_fitted = True

    # --------------------------------------------------------------- feature --

    @torch.no_grad()
    def _extract(self, tensor: torch.Tensor) -> torch.Tensor:
        self.backbone(tensor)
        l2 = self._f2
        l3 = F.interpolate(self._f3, size=l2.shape[-2:], mode="bilinear", align_corners=False)
        return torch.cat([l2, l3], dim=1)

    def _to_patches(self, feats: torch.Tensor) -> torch.Tensor:
        B, C, h, w = feats.shape
        return feats[0].permute(1, 2, 0).reshape(-1, C)

    def _crop_to_tensor(self, crop_bgr: np.ndarray) -> torch.Tensor:
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        return self.transform(pil).unsqueeze(0).to(self.device)

    # ------------------------------------------------------------------- fit --

    def fit(self, images: list[bytes], roi: tuple[float, float, float, float]) -> dict:
        self.registered_roi = roi
        roi_x, roi_y, roi_w, roi_h = roi

        patches_list = []
        crops_for_template: list[np.ndarray] = []

        for img_bytes in images:
            full = self._decode(img_bytes)
            crop = self._crop_by_roi(full, roi)
            crops_for_template.append(crop)

            tensor = self._crop_to_tensor(crop)
            feats = self._extract(tensor)
            patches_list.append(self._to_patches(feats))

        # Build mean template for matching
        self.reference_template = np.mean(crops_for_template, axis=0).astype(np.uint8)

        bank = torch.cat(patches_list, dim=0)
        if bank.shape[0] > 10_000:
            idx = torch.randperm(bank.shape[0])[:10_000]
            bank = bank[idx]
        self.feature_bank = bank
        self.is_fitted = True

        scores = [self._score_crop(crop) for crop in crops_for_template]
        self.threshold = float(np.percentile(scores, 99)) * 1.25
        self._save()

        return {"bank_size": int(bank.shape[0]), "threshold": round(self.threshold, 4)}

    def _score_crop(self, crop_bgr: np.ndarray) -> float:
        tensor = self._crop_to_tensor(crop_bgr)
        feats = self._extract(tensor)
        patches = self._to_patches(feats)
        dist = torch.cdist(patches, self.feature_bank)
        return float(dist.min(dim=1).values.max())

    # --------------------------------------------------------------- predict --

    def predict(self, img_bytes: bytes) -> dict:
        if not self.is_fitted:
            raise RuntimeError("良品が未登録です")

        full = self._decode(img_bytes)
        fh, fw = full.shape[:2]

        crop, match_roi, confidence = self._match_and_crop(full)

        tensor = self._crop_to_tensor(crop)
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
            "heatmap": self._colorize(anomaly_map),
            "match_confidence": round(float(confidence), 3),
            "match_roi": {
                "x": round(match_roi[0] / fw, 4),
                "y": round(match_roi[1] / fh, 4),
                "w": round(match_roi[2] / fw, 4),
                "h": round(match_roi[3] / fh, 4),
            },
        }

    # -------------------------------------------------------- matching/crop --

    def _match_and_crop(
        self, full: np.ndarray
    ) -> tuple[np.ndarray, tuple[int, int, int, int], float]:
        """Return (crop_bgr, (x,y,w,h)_px, confidence)."""
        fallback = self._crop_by_roi(full, self.registered_roi)
        fh, fw = full.shape[:2]
        rx = int(self.registered_roi[0] * fw)
        ry = int(self.registered_roi[1] * fh)
        rw = int(self.registered_roi[2] * fw)
        rh = int(self.registered_roi[3] * fh)
        fallback_roi = (rx, ry, rw, rh)

        if self.reference_template is None:
            return fallback, fallback_roi, 0.0

        tmpl = self.reference_template
        th, tw = tmpl.shape[:2]

        if full.shape[0] < th or full.shape[1] < tw:
            return fallback, fallback_roi, 0.0

        gray_full = cv2.cvtColor(full, cv2.COLOR_BGR2GRAY)
        gray_tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)

        result = cv2.matchTemplate(gray_full, gray_tmpl, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, max_loc = cv2.minMaxLoc(result)

        if confidence < MATCH_THRESHOLD:
            return fallback, fallback_roi, float(confidence)

        x, y = max_loc
        crop = full[y: y + th, x: x + tw]
        return crop, (x, y, tw, th), float(confidence)

    # ---------------------------------------------------------------- utils --

    @staticmethod
    def _decode(img_bytes: bytes) -> np.ndarray:
        arr = np.frombuffer(img_bytes, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    @staticmethod
    def _crop_by_roi(
        img: np.ndarray, roi: tuple[float, float, float, float]
    ) -> np.ndarray:
        h, w = img.shape[:2]
        x = int(roi[0] * w)
        y = int(roi[1] * h)
        cw = int(roi[2] * w)
        ch = int(roi[3] * h)
        return img[y: y + ch, x: x + cw]

    def _colorize(self, anomaly_map: np.ndarray) -> str:
        am = anomaly_map.astype(np.float32)
        if am.max() > am.min():
            am_n = (am - am.min()) / (am.max() - am.min())
        else:
            am_n = np.zeros_like(am)

        am_u8 = (am_n * 255).astype(np.uint8)
        bgr = cv2.applyColorMap(am_u8, cv2.COLORMAP_JET)
        rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
        alpha = np.clip((am_n - 0.2) * (255 / 0.8), 0, 200).astype(np.uint8)
        rgba[:, :, 3] = alpha
        rgba = cv2.resize(rgba, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_LINEAR)
        _, buf = cv2.imencode(".png", rgba)
        return base64.b64encode(buf.tobytes()).decode()
