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

Vertex = dict  # {"x": float, "y": float}  in 0-1 relative coords


def auto_segment(img_bytes: bytes) -> list[Vertex]:
    """Foreground segmentation. Returns polygon vertices in 0-1 coords.

    Mask-initialized GrabCut (border=definite BG, center=probable FG) is
    far more reliable than a plain rect init. The seed mask is refined with
    a border-vs-object contrast estimate before running GrabCut.
    """
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("画像のデコードに失敗しました")
    h, w = img.shape[:2]

    # Downscale to max 512px (better edges than 400px, still fast)
    scale = min(1.0, 512 / max(h, w))
    sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
    small = cv2.resize(img, (sw, sh)) if scale < 1.0 else img.copy()

    fg = _grabcut_mask(small, sw, sh)

    # If GrabCut produced a tiny/empty result, fall back to contrast threshold
    if fg is None or cv2.countNonZero(fg) < 0.02 * sw * sh:
        fg = _contrast_mask(small, sw, sh)
    if fg is None or cv2.countNonZero(fg) < 0.02 * sw * sh:
        return _default_box()

    # Morphological cleanup + keep largest blob only
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k)

    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return _default_box()

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.02 * sw * sh:
        return _default_box()

    # Approximate to a draggable polygon (~6-14 vertices that hug the shape)
    peri = cv2.arcLength(largest, True)
    eps = 0.01 * peri
    approx = cv2.approxPolyDP(largest, eps, True)
    while len(approx) > 14 and eps < 0.15 * peri:
        eps *= 1.25
        approx = cv2.approxPolyDP(largest, eps, True)
    if len(approx) < 3:
        hull = cv2.convexHull(largest)
        approx = cv2.approxPolyDP(hull, 0.05 * cv2.arcLength(hull, True), True)
    if len(approx) < 3:
        return _default_box()

    return [{"x": round(float(pt[0][0] / sw), 4), "y": round(float(pt[0][1] / sh), 4)} for pt in approx]


def _grabcut_mask(small, sw, sh):
    """Mask-initialized GrabCut. Returns a uint8 foreground mask (255/0)."""
    mask = np.full((sh, sw), cv2.GC_PR_BGD, np.uint8)

    # Outer ring = definite background
    bw = max(2, int(min(sw, sh) * 0.05))
    mask[:bw, :] = cv2.GC_BGD
    mask[-bw:, :] = cv2.GC_BGD
    mask[:, :bw] = cv2.GC_BGD
    mask[:, -bw:] = cv2.GC_BGD

    # Central ellipse = probable foreground
    cv2.ellipse(mask, (sw // 2, sh // 2),
                (int(sw * 0.32), int(sh * 0.32)), 0, 0, 360, cv2.GC_PR_FGD, -1)

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(small, mask, None, bgd, fgd, 8, cv2.GC_INIT_WITH_MASK)
    except Exception:
        return None
    return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


def _contrast_mask(small, sw, sh):
    """Fallback: separate object from background using border colour as BG ref."""
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # Estimate background brightness from the border ring
    bw = max(2, int(min(sw, sh) * 0.05))
    ring = np.concatenate([
        gray[:bw, :].ravel(), gray[-bw:, :].ravel(),
        gray[:, :bw].ravel(), gray[:, -bw:].ravel(),
    ])
    bg_mean = float(np.mean(ring))

    # Object = pixels differing enough from the background brightness
    diff = cv2.absdiff(gray, np.full_like(gray, int(bg_mean)))
    _, fg = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return fg


def _default_box() -> list[Vertex]:
    return [{"x": 0.15, "y": 0.15}, {"x": 0.85, "y": 0.15},
            {"x": 0.85, "y": 0.85}, {"x": 0.15, "y": 0.85}]


class PatchCoreInspector:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.feature_bank: torch.Tensor | None = None
        self.threshold: float | None = None
        self.registered_contour: list[Vertex] | None = None
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
            pickle.dump({
                "bank": self.feature_bank.cpu(),
                "threshold": self.threshold,
                "contour": self.registered_contour,
            }, f)

    def _load(self):
        if SAVE_PATH.exists():
            try:
                with open(SAVE_PATH, "rb") as f:
                    s = pickle.load(f)
                self.feature_bank = s["bank"].to(self.device)
                self.threshold = s["threshold"]
                self.registered_contour = s.get("contour", None)
                self.is_fitted = True
            except Exception:
                pass

    @torch.no_grad()
    def _extract(self, tensor: torch.Tensor) -> torch.Tensor:
        self.backbone(tensor)
        l2 = self._f2
        l3 = F.interpolate(self._f3, size=l2.shape[-2:], mode="bilinear", align_corners=False)
        return torch.cat([l2, l3], dim=1)

    def _apply_contour_mask(self, img_bgr: np.ndarray, vertices: list[Vertex]) -> np.ndarray:
        h, w = img_bgr.shape[:2]
        pts = np.array([[int(v["x"] * w), int(v["y"] * h)] for v in vertices], dtype=np.int32)
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 255)
        result = img_bgr.copy()
        result[mask == 0] = 128  # neutral gray background
        return result

    def _preprocess(self, data: bytes, vertices: list[Vertex] | None = None) -> torch.Tensor:
        if vertices:
            nparr = np.frombuffer(data, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            img_bgr = self._apply_contour_mask(img_bgr, vertices)
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(img_rgb)
        else:
            pil = Image.open(io.BytesIO(data)).convert("RGB")
        return self.transform(pil).unsqueeze(0).to(self.device)

    def _to_patches(self, feats: torch.Tensor) -> torch.Tensor:
        B, C, h, w = feats.shape
        return feats[0].permute(1, 2, 0).reshape(-1, C)

    def fit(self, images: list[bytes], contour: list[Vertex] | None = None) -> dict:
        self.registered_contour = contour
        patches_list = []
        for img_bytes in images:
            tensor = self._preprocess(img_bytes, contour)
            feats = self._extract(tensor)
            patches_list.append(self._to_patches(feats))

        bank = torch.cat(patches_list, dim=0)
        if bank.shape[0] > 10_000:
            idx = torch.randperm(bank.shape[0])[:10_000]
            bank = bank[idx]

        self.feature_bank = bank
        self.is_fitted = True

        scores = [self._score(img_bytes, contour) for img_bytes in images]
        self.threshold = float(np.percentile(scores, 99)) * 1.25
        self._save()

        return {"bank_size": int(bank.shape[0]), "threshold": round(self.threshold, 4)}

    def _score(self, img_bytes: bytes, vertices: list[Vertex] | None = None) -> float:
        tensor = self._preprocess(img_bytes, vertices)
        feats = self._extract(tensor)
        patches = self._to_patches(feats)
        dist = torch.cdist(patches, self.feature_bank)
        return float(dist.min(dim=1).values.max())

    def predict(self, img_bytes: bytes) -> dict:
        if not self.is_fitted:
            raise RuntimeError("良品が未登録です")

        tensor = self._preprocess(img_bytes, self.registered_contour)
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
        }

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
