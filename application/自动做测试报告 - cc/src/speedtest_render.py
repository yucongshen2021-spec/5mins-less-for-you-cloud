"""Speedtest screenshot parameter replacement — component-level rebuilder."""
from __future__ import annotations

import io, math, os, sys
from pathlib import Path
import re
from dataclasses import dataclass, field
from typing import Optional

import cv2
import easyocr
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ── Font Registry ─────────────────────────────────────────────────────

class FontRegistry:
    """Scans system fonts directory, maps weight names to file paths."""

    _instance: Optional["FontRegistry"] = None

    def __init__(self):
        self._fonts: dict[str, str] = {}  # weight_name -> file_path
        self._scan()

    def _scan(self):
        fonts_dir = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
        if not fonts_dir.is_dir():
            fonts_dir = Path("/usr/share/fonts")

        for fpath in fonts_dir.glob("*.ttf"):
            name = fpath.stem.lower().replace(" ", "")
            # Segoe UI Light → segoeuil.ttf
            if "segoeuil" in name:
                self._fonts["segoeui_light"] = str(fpath)
            elif "segoeuisl" in name:
                self._fonts["segoeui_semilight"] = str(fpath)
            elif name == "segoeui":
                self._fonts["segoeui_normal"] = str(fpath)
            elif "segoeuib" in name:
                self._fonts["segoeui_bold"] = str(fpath)
            elif name == "arial":
                self._fonts["arial_normal"] = str(fpath)
            elif "arialbd" in name:
                self._fonts["arial_bold"] = str(fpath)
            elif "helvetica" in name and "light" in name:
                self._fonts["helvetica_light"] = str(fpath)
            elif "helvetica" in name:
                self._fonts["helvetica_normal"] = str(fpath)
            elif "roboto" in name and "light" in name:
                self._fonts["roboto_light"] = str(fpath)
            elif "roboto" in name:
                self._fonts["roboto_normal"] = str(fpath)

    @classmethod
    def instance(cls) -> "FontRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get(self, weight: str = "normal") -> str:
        """Get font file path for a weight name. Raises RuntimeError if not found."""
        # Priority: segoeui_{weight} > segoeui_normal > arial_normal
        candidates = [
            f"segoeui_{weight}",
            "segoeui_normal",
            "arial_normal",
        ]
        for c in candidates:
            if c in self._fonts:
                return self._fonts[c]
        available = list(self._fonts.keys())
        raise RuntimeError(
            f"No suitable font found for weight='{weight}'. "
            f"Available: {available}. Install Segoe UI font family."
        )

    def load(self, size_px: int, weight: str = "normal") -> ImageFont.FreeTypeFont:
        """Load a PIL ImageFont at the given size and weight."""
        path = self.get(weight)
        return ImageFont.truetype(path, size_px)


# ── EasyOCR Reader (Lazy Singleton) ─────────────────────────────────────

_ocr_reader: Optional[easyocr.Reader] = None


def _get_ocr() -> easyocr.Reader:
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _ocr_reader


# ── Detected Field Dataclass ────────────────────────────────────────────

@dataclass
class DetectedField:
    """One text region found by OCR."""
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2) tight bbox
    text: str
    confidence: float
    is_dynamic: bool = False  # True = numeric value to replace
    font_size_est: int = 12
    fg_color: tuple[int, int, int] = (255, 255, 255)


# ── OCR Detection ───────────────────────────────────────────────────────

def detect_fields(cv_bgr: np.ndarray) -> list[DetectedField]:
    """
    OCR-detect all text regions. Classify as dynamic (numeric/replaceable)
    or static (labels, icons — to protect).
    """
    reader = _get_ocr()
    img_rgb = cv2.cvtColor(cv_bgr, cv2.COLOR_BGR2RGB)
    raw = reader.readtext(img_rgb, detail=1)

    fields = []
    for bbox_pts, text, conf in raw:
        if conf < 0.5:
            continue
        # Convert 4-point bbox to axis-aligned rectangle
        xs = [p[0] for p in bbox_pts]
        ys = [p[1] for p in bbox_pts]
        x1, x2 = int(min(xs)), int(max(xs))
        y1, y2 = int(min(ys)), int(max(ys))

        text_clean = text.strip()

        # Classify: dynamic if it looks like a numeric value
        is_dynamic = bool(re.match(
            r"^[\d,.]+(\s*(Mbps|ms|%))?$", text_clean
        ))

        # Sample foreground color from text region
        roi = cv_bgr[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(float)
        bg_val = float(np.median(np.concatenate([
            gray[:2, :].flatten(), gray[-2:, :].flatten(),
            gray[:, :2].flatten(), gray[:, -2:].flatten()
        ])))
        fg_mask = np.abs(gray - bg_val) > 12
        fg_pixels = roi[fg_mask]
        if len(fg_pixels) > 5:
            fg_bgr = np.median(fg_pixels, axis=0).astype(int)
            fg_color = (int(fg_bgr[2]), int(fg_bgr[1]), int(fg_bgr[0]))
        else:
            fg_color = (255, 255, 255)

        fields.append(DetectedField(
            bbox=(x1, y1, x2, y2),
            text=text_clean,
            confidence=conf,
            is_dynamic=is_dynamic,
            font_size_est=max(8, y2 - y1),
            fg_color=fg_color,
        ))

    return fields


# ── Field Classification ────────────────────────────────────────────────

def classify_dynamic_fields(
    fields: list[DetectedField],
    img_w: int, img_h: int
) -> dict[str, DetectedField]:
    """
    Map detected dynamic fields to semantic keys based on position.
    Uses proximity to static label text and font size heuristics.
    """
    center_x = img_w // 2
    top_third = img_h // 3
    mid = img_h // 2

    result: dict[str, DetectedField] = {}
    dyn = [f for f in fields if f.is_dynamic]

    # Download speed: largest font, center-top
    large = [f for f in dyn if f.font_size_est > 25]
    medium = [f for f in dyn if 10 <= f.font_size_est <= 25]
    small = [f for f in dyn if f.font_size_est < 10]

    if large:
        large.sort(key=lambda f: f.bbox[1])
        result["download"] = large[0]

    # Upload speed: medium font, lower center area
    if medium:
        medium.sort(key=lambda f: f.bbox[1], reverse=True)
        for f in medium:
            cx = (f.bbox[0] + f.bbox[2]) // 2
            cy = (f.bbox[1] + f.bbox[3]) // 2
            if cy > top_third + 40:
                result["upload"] = f
                break

    # Ping/jitter: small font, left side
    left_small = [f for f in small if (f.bbox[0] + f.bbox[2]) // 2 < center_x - 50]
    left_small.sort(key=lambda f: f.bbox[1])
    if len(left_small) >= 1:
        result["ping"] = left_small[0]
    if len(left_small) >= 2:
        result["jitter"] = left_small[1]

    # Server/ISP: small font, bottom area
    bottom_small = [f for f in small if f.bbox[1] > mid]
    bottom_small.sort(key=lambda f: f.bbox[1])
    if len(bottom_small) >= 1:
        result["server"] = bottom_small[0]
    if len(bottom_small) >= 2:
        result["isp"] = bottom_small[1]

    return result


# ── Protection Mask ─────────────────────────────────────────────────────

def build_protection_mask(fields: list[DetectedField],
                          img_h: int, img_w: int) -> np.ndarray:
    """
    Create a binary mask marking ALL static elements as protected.
    Static = non-dynamic OCR detections (labels, icons, buttons).
    These regions MUST NOT be inpainted or modified.
    Returns mask where 255 = PROTECTED (do not modify).
    """
    mask = np.zeros((img_h, img_w), dtype=np.uint8)
    for f in fields:
        if f.is_dynamic:
            continue
        x1, y1, x2, y2 = f.bbox
        x1 = max(0, x1 - 3)
        y1 = max(0, y1 - 3)
        x2 = min(img_w, x2 + 3)
        y2 = min(img_h, y2 + 3)
        mask[y1:y2, x1:x2] = 255
    return mask
