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


# ── Font Sizing — Iterative Search ───────────────────────────────────────

def find_exact_font_size(target_char_w: int, target_char_h: int,
                         sample_char: str = "8",
                         weight: str = "normal") -> tuple[ImageFont.FreeTypeFont, int]:
    """
    Binary search for the Pillow font size that produces a character
    closest to target_char_w x target_char_h.
    Returns (font, actual_size_px) with error <= +/-1px.
    """
    registry = FontRegistry.instance()

    lo, hi = 4, 200
    best_font = None
    best_size = 0
    best_diff = float("inf")

    for _ in range(12):  # Binary search iterations
        mid = (lo + hi) // 2
        font = registry.load(mid, weight)
        bb = font.getbbox(sample_char)
        actual_w = bb[2] - bb[0]
        actual_h = bb[3] - bb[1]
        diff = abs(actual_w - target_char_w) + abs(actual_h - target_char_h)

        if diff < best_diff:
            best_diff = diff
            best_font = font
            best_size = mid

        if abs(actual_h - target_char_h) <= 1 and abs(actual_w - target_char_w) <= 1:
            break  # Good enough

        if actual_h < target_char_h:
            lo = mid + 1
        else:
            hi = mid - 1

    if best_font is None:
        best_font = registry.load(target_char_h, weight)

    return best_font, best_size


# ── Baseline Computation ─────────────────────────────────────────────────

def compute_baseline_y(field: DetectedField, font: ImageFont.FreeTypeFont) -> int:
    """
    Compute the true baseline y-coordinate using font metrics:
    baseline = bbox_bottom - descent

    Uses per-character font bbox to determine the actual descent
    for the specific text (e.g., digits have zero descent, while 'g'
    extends below the baseline).
    """
    ascent, _descent = font.getmetrics()
    _, y1, _, y2 = field.bbox
    char_h = y2 - y1

    # Get the font's actual pixel bbox for this specific character
    bb = font.getbbox(field.text)
    char_h_px = bb[3] - bb[1]
    # Per-character descent: how far the glyph extends below the baseline
    char_descent = max(0, bb[3] - ascent)

    if char_h > 0 and char_h_px > 0:
        scale = char_h / char_h_px
        pix_descent = int(char_descent * scale)
    else:
        pix_descent = 2
    return y2 - pix_descent


# ── Constants ─────────────────────────────────────────────────────────────

UPSCALE = 8
INPAINT_RADIUS = 3
MASK_THRESHOLD = 10


# ── Single-Buffer Field Replacement ───────────────────────────────────────

def replace_single_field(
    cv_bgr: np.ndarray,              # Single working buffer (BGR, modified in-place)
    field: DetectedField,            # OCR-detected field to replace
    new_text: str,                   # New text to render
    protection_mask: np.ndarray,     # Static elements (255 = do not touch)
    weight: str = "normal",
) -> np.ndarray:
    """
    Replace one text field using single image buffer.
    1. Extract character mask from OCR bbox (minus protection)
    2. Inpaint ONLY those pixels via TELEA
    3. Find exact font size via binary search (find_exact_font_size)
    4. Render new text at 8x on transparent RGBA canvas → Lanczos downscale to 1x
    5. Compute baseline position (compute_baseline_y)
    6. Alpha-composite new text directly onto cv_bgr (BGR)
    Returns cv_bgr (same buffer, modified).
    """
    h, w = cv_bgr.shape[:2]
    x1, y1, x2, y2 = field.bbox

    # ── 1. Extract character mask ──
    roi = cv_bgr[y1:y2, x1:x2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(float)

    strips = []
    if roi.shape[0] > 2:
        strips.extend([gray[0, :].flatten(), gray[-1, :].flatten()])
    if roi.shape[1] > 2:
        strips.extend([gray[:, 0].flatten(), gray[:, -1].flatten()])
    bg_val = float(np.median(np.concatenate(strips))) if strips else 127

    char_mask = (np.abs(gray - bg_val) > MASK_THRESHOLD).astype(np.uint8) * 255

    # ── 2. Subtract protection mask ──
    prot_roi = protection_mask[y1:y2, x1:x2]
    char_mask = cv2.bitwise_and(char_mask, cv2.bitwise_not(prot_roi))

    if char_mask.sum() < 10:
        return cv_bgr

    # ── 3. Inpaint only character pixels ──
    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[y1:y2, x1:x2] = char_mask
    cv_bgr = cv2.inpaint(cv_bgr, full_mask, INPAINT_RADIUS, cv2.INPAINT_TELEA)

    # ── 4. Measure original character dimensions ──
    ys, xs = np.where(char_mask > 0)
    char_w = int(np.max(xs) - np.min(xs) + 1) if len(ys) > 0 else field.font_size_est
    char_h = field.font_size_est

    # ── 5. Find matching font ──
    font, actual_size = find_exact_font_size(char_w, char_h, "8", weight)

    # ── 6. Render at 8x → Lanczos ──
    scale = UPSCALE
    big_size = actual_size * scale
    big_font = FontRegistry.instance().load(big_size, weight)

    bb = big_font.getbbox(new_text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    ox, oy = bb[0], bb[1]
    pad = max(4, int(big_size * 0.12))

    img_8x = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img_8x)
    draw.text((pad - ox, pad - oy), new_text, fill=field.fg_color + (255,), font=big_font)

    ow = max(1, (tw + pad * 2) // scale)
    oh = max(1, (th + pad * 2) // scale)
    text_1x = img_8x.resize((ow, oh), Image.LANCZOS)

    # ── 7. Place: center horizontally, baseline-aligned vertically ──
    baseline_y = compute_baseline_y(field, font)
    orig_cx = (x1 + x2) // 2
    px = orig_cx - text_1x.width // 2
    py = baseline_y - int(actual_size * 0.7)
    py = max(y1 - 2, min(y2 - text_1x.height + 2, py))

    # ── 8. Alpha-composite onto cv_bgr (BGR) ──
    text_arr = np.array(text_1x)  # RGBA
    text_alpha = text_arr[:, :, 3].astype(float) / 255.0
    text_rgb = text_arr[:, :, :3].astype(float)

    tx1 = max(0, px); ty1 = max(0, py)
    tx2 = min(w, px + text_1x.width); ty2 = min(h, py + text_1x.height)
    sx1 = tx1 - px; sy1 = ty1 - py

    for c in range(3):
        patch = cv_bgr[ty1:ty2, tx1:tx2, c].astype(float)
        ap = text_alpha[sy1:sy1+(ty2-ty1), sx1:sx1+(tx2-tx1)]
        tp = text_rgb[sy1:sy1+(ty2-ty1), sx1:sx1+(tx2-tx1), 2-c]  # RGB→BGR
        cv_bgr[ty1:ty2, tx1:tx2, c] = np.clip(
            patch * (1 - ap) + tp * ap, 0, 255
        ).astype(np.uint8)

    return cv_bgr


# ── Spectral Texture Extraction ────────────────────────────────────────────

def extract_noise_spectrum(
    cv_bgr: np.ndarray,
    x1: int, y1: int, x2: int, y2: int,
    band_width: int = 30
) -> float:
    """
    Extract noise stddev from an annular region around the modified area.
    """
    h, w = cv_bgr.shape[:2]
    samples = []
    strips = [
        (max(0, y1 - band_width), max(0, y1), x1, x2),
        (min(h, y2), min(h, y2 + band_width), x1, x2),
        (y1, y2, max(0, x1 - band_width), max(0, x1)),
        (y1, y2, min(w, x2), min(w, x2 + band_width)),
    ]
    for sy1, sy2, sx1, sx2 in strips:
        if sy2 > sy1 and sx2 > sx1:
            patch = cv_bgr[sy1:sy2, sx1:sx2].astype(float)
            if patch.size > 0:
                samples.append(patch)
    if not samples:
        return 1.0
    all_pixels = np.concatenate([s.flatten() for s in samples])
    return float(np.std(all_pixels))


def apply_spectral_texture(
    cv_bgr: np.ndarray,
    regions: list[tuple[int, int, int, int]],
    reference: np.ndarray,
    opacity: float = 0.04,
) -> np.ndarray:
    """
    Extract noise stddev from surrounding pixels of each region
    in the reference image, generate matching noise, blend into cv_bgr.
    """
    if not regions:
        return cv_bgr
    result = cv_bgr.copy().astype(np.float32)
    h, w = cv_bgr.shape[:2]
    for x1, y1, x2, y2 in regions:
        x1, y1 = max(0, x1 - 4), max(0, y1 - 4)
        x2, y2 = min(w, x2 + 4), min(h, y2 + 4)
        if x2 <= x1 or y2 <= y1:
            continue
        noise_std = extract_noise_spectrum(reference, x1, y1, x2, y2)
        rh, rw = y2 - y1, x2 - x1
        noise = np.random.normal(0, noise_std, (rh, rw, 3)).astype(np.float32)
        mask = np.ones((rh, rw), dtype=np.float32)
        mask = cv2.GaussianBlur(mask, (7, 7), 2)
        mask = mask[:, :, np.newaxis]
        result[y1:y2, x1:x2] = (
            result[y1:y2, x1:x2] * (1 - mask * opacity)
            + result[y1:y2, x1:x2] * mask * (1 - opacity)
            + noise * mask * opacity
        )
    return np.clip(result, 0, 255).astype(np.uint8)


# ── Quality Verification ───────────────────────────────────────────────────

def verify_region(cv_bgr: np.ndarray, x1: int, y1: int,
                  x2: int, y2: int) -> bool:
    """
    Compare edge density in region vs surrounding background strips.
    """
    h, w = cv_bgr.shape[:2]
    x1 = max(8, x1); y1 = max(8, y1)
    x2 = min(w - 8, x2); y2 = min(h - 8, y2)
    if x2 <= x1 + 5 or y2 <= y1 + 5:
        return True
    gray = cv2.cvtColor(cv_bgr, cv2.COLOR_BGR2GRAY).astype(float)
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    edge = np.abs(gx) + np.abs(gy)
    region_edges = float(np.mean(edge[y1:y2, x1:x2]))
    above = edge[max(0, y1 - 12):max(0, y1 - 2), x1:x2]
    below = edge[min(h, y2 + 2):min(h, y2 + 12), x1:x2]
    surround = np.concatenate([above.flatten(), below.flatten()]) if above.size + below.size > 0 else np.array([region_edges])
    surround_edges = float(np.mean(surround))
    ratio = region_edges / max(surround_edges, 0.3)
    return 0.15 < ratio < 6.0


# ── Full Pipeline Orchestrator ────────────────────────────────────────────

def generate_speedtest_image(
    template_path: Path,
    output_path: Path,
    download_mbps: str,
    upload_mbps: str,
    ping_ms: str,
    jitter_ms: str,
    server: str = "FastIP SpeedTest",
    isp: str = "China Telecom",
    ip_addr: str = "192.168.5.10",
    location: str = "Shenzhen",
    max_retries: int = 3,
) -> Path:
    """
    Full pipeline on single image buffer:
    OCR detect -> classify -> protect -> inpaint -> render -> texture -> verify -> retry.
    """
    # Use np.fromfile + imdecode for Unicode path support (cv2.imread fails on CJK paths)
    buf = np.fromfile(str(template_path), dtype=np.uint8)
    cv_bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    h, w = cv_bgr.shape[:2]

    # Phase 1: OCR detection + classification
    fields = detect_fields(cv_bgr)
    dyn = classify_dynamic_fields(fields, w, h)
    protection_mask = build_protection_mask(fields, h, w)

    if not dyn:
        # Use imencode for Unicode path support
        success, encoded = cv2.imencode(".png", cv_bgr)
        if success:
            output_path.write_bytes(encoded.tobytes())
        return output_path

    # Build value map — download as SINGLE visual object (not split int/frac)
    values = {
        "download": f"{download_mbps} Mbps",
        "upload": f"{upload_mbps} Mbps",
        "ping": f"{ping_ms} ms",
        "jitter": f"{jitter_ms} ms",
        "server": server,
        "isp": f"{isp}  {ip_addr}  {location}",
    }

    # Phase 2: Process each dynamic field on single buffer
    cv_working = cv_bgr.copy()
    modified_regions = []

    for key, field in dyn.items():
        if key not in values:
            continue
        weight = "light" if field.font_size_est > 30 else "normal"
        cv_working = replace_single_field(
            cv_working, field, values[key], protection_mask, weight
        )
        modified_regions.append(field.bbox)

    # Phase 3: Spectral texture on modified regions
    if modified_regions:
        cv_working = apply_spectral_texture(cv_working, modified_regions, cv_bgr)

    # Phase 4: Verify + retry
    for attempt in range(max_retries):
        all_pass = True
        for key, field in dyn.items():
            if key not in values:
                continue
            if not verify_region(cv_working, field.bbox[0], field.bbox[1],
                                 field.bbox[2], field.bbox[3]):
                all_pass = False
                break
        if all_pass:
            break
        cv_working = apply_spectral_texture(
            cv_working, modified_regions, cv_bgr,
            opacity=0.03 + attempt * 0.015
        )

    # Use imencode for Unicode path support
    success, encoded = cv2.imencode(".png", cv_working)
    if success:
        output_path.write_bytes(encoded.tobytes())
    return output_path
