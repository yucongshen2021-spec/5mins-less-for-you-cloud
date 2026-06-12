"""
Speedtest screenshot parameter replacement — production pipeline.

Architecture (hybrid v5+v6):
  1. Calibrated field ROIs (fixed template, pixel-precise from analysis)
  2. Protection mask for static elements (gauge, icons, labels, panels)
  3. Inpaint: TELEA on character pixels only (per-field mask from ROI, minus protection)
  4. Render: font registry → iterative size search → 8x supersample → Lanczos
  5. Place: metrics-based baseline + original alignment
  6. Texture: spectral noise from surrounding pixels
  7. Verify: Sobel edge density ratio check → retry with adjusted opacity

Single image buffer (np.ndarray BGR) throughout.
Static elements (icons, labels, separators, decorative graphics) are NEVER touched.
"""

from __future__ import annotations
import io, math, os, sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

# ── Constants ──────────────────────────────────────────────────────────
UPSCALE = 8
INPAINT_RADIUS = 4
MASK_THRESHOLD = 10
NOISE_OPACITY = 0.035
MAX_RETRIES = 3

# ── Font Registry ─────────────────────────────────────────────────────

class _FontRegistry:
    """Singleton: scans system fonts, maps weight names to file paths."""
    _instance: Optional["_FontRegistry"] = None

    def __init__(self):
        self._fonts: dict[str, str] = {}
        fonts_dir = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
        if not fonts_dir.is_dir():
            fonts_dir = Path("/usr/share/fonts")
        for fp in fonts_dir.glob("*.ttf"):
            n = fp.stem.lower().replace(" ", "")
            if "segoeuil" in n:       self._fonts["segoeui_light"] = str(fp)
            elif "segoeuisl" in n:    self._fonts["segoeui_semilight"] = str(fp)
            elif n == "segoeui":      self._fonts["segoeui_normal"] = str(fp)
            elif "segoeuib" in n:     self._fonts["segoeui_bold"] = str(fp)
            elif n == "arial":        self._fonts["arial_normal"] = str(fp)
            elif "arialbd" in n:      self._fonts["arial_bold"] = str(fp)
            elif "helvetica" in n and "light" in n: self._fonts["helvetica_light"] = str(fp)
            elif "helvetica" in n:    self._fonts["helvetica_normal"] = str(fp)

    @classmethod
    def instance(cls):
        if cls._instance is None: cls._instance = cls()
        return cls._instance

    def get(self, weight: str = "normal") -> str:
        for c in [f"segoeui_{weight}", "segoeui_normal", "arial_normal"]:
            if c in self._fonts: return self._fonts[c]
        raise RuntimeError(f"No font for weight='{weight}'. Available: {list(self._fonts.keys())}")

    def load(self, size: int, weight: str = "normal") -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.get(weight), size)


# ── Calibrated field definitions (pixel analysis, fixed template) ──────

@dataclass
class _FieldSpec:
    key: str
    x1: int; y1: int; x2: int; y2: int
    font_size_px: int
    fg_color: tuple
    weight: str
    alignment: str  # "left" | "center" | "right"

FIELDS = [
    _FieldSpec("download_int",  222, 40,  418, 80,  46, (250,250,251), "light",  "center"),
    _FieldSpec("download_frac", 425, 44,  520, 76,  22, (210,210,215), "light",  "left"),
    _FieldSpec("upload_speed",  150, 237, 278, 258, 15, (35,165,230),  "normal", "center"),
    _FieldSpec("ping_value",    137, 143, 193, 159, 12, (195,205,220), "normal", "left"),
    _FieldSpec("jitter_value",  137, 154, 193, 173, 12, (195,205,220), "normal", "left"),
    _FieldSpec("server_name",   156, 268, 295, 283, 10, (155,165,195), "normal", "left"),
    _FieldSpec("isp_info",      126, 293, 240, 306, 10, (90,92,113),   "normal", "left"),
]

# Static element protection regions (MUST NOT be modified)
PROTECT = [
    (195, 14,  530, 36),   # Top logo
    (195, 85,  530, 130),  # Gauge area
    (20,  155, 105, 240),  # Left icons + labels
    (115, 130, 200, 145),  # PING/JITTER labels
    (30,  230, 105, 260),  # Upload label area
    (640, 192, 706, 232),  # Right panel
    (0,   0,   723, 12),   # Top edge
    (0,   314, 723, 326),  # Bottom edge
]


# ── Mask + inpaint ─────────────────────────────────────────────────────

def _text_mask(cv_bgr: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
    """Pixel-precise binary mask of text in ROI."""
    h, w = cv_bgr.shape[:2]; x1, y1 = max(1,x1), max(1,y1); x2, y2 = min(w-1,x2), min(h-1,y2)
    roi = cv_bgr[y1:y2, x1:x2]; gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(float)
    strips = []
    if gray.shape[0] > 2: strips.extend([gray[0,:].flatten(), gray[-1,:].flatten()])
    if gray.shape[1] > 2: strips.extend([gray[:,0].flatten(), gray[:,-1].flatten()])
    bg = float(np.median(np.concatenate(strips))) if strips else 127
    return (np.abs(gray - bg) > MASK_THRESHOLD).astype(np.uint8) * 255


def _inpaint_field(cv_bgr: np.ndarray, field: _FieldSpec) -> np.ndarray:
    """Inpaint only the text pixels of this field. Protection regions excluded."""
    h, w = cv_bgr.shape[:2]
    mask = _text_mask(cv_bgr, field.x1, field.y1, field.x2, field.y2)
    if mask.sum() < 10: return cv_bgr
    full = np.zeros((h, w), dtype=np.uint8)
    ey = min(field.y1 + mask.shape[0], h); ex = min(field.x1 + mask.shape[1], w)
    full[field.y1:ey, field.x1:ex] = mask[:ey-field.y1, :ex-field.x1]
    # Subtract protection
    for px1, py1, px2, py2 in PROTECT:
        full[max(0,py1):min(h,py2), max(0,px1):min(w,px2)] = 0
    if full.sum() < 10: return cv_bgr
    return cv2.inpaint(cv_bgr, full, INPAINT_RADIUS, cv2.INPAINT_TELEA)


# ── Font sizing ────────────────────────────────────────────────────────

def _find_font(target_w: int, target_h: int, weight: str = "normal"
               ) -> tuple[ImageFont.FreeTypeFont, int]:
    """Binary search for font size matching target char dimensions."""
    reg = _FontRegistry.instance()
    lo, hi = 4, 200; best_f, best_s, best_d = None, 0, float("inf")
    for _ in range(12):
        mid = (lo+hi)//2; f = reg.load(mid, weight)
        bb = f.getbbox("8"); dw = abs((bb[2]-bb[0])-target_w); dh = abs((bb[3]-bb[1])-target_h)
        if dw+dh < best_d: best_f, best_s, best_d = f, mid, dw+dh
        if dw <= 1 and dh <= 1: break
        if (bb[3]-bb[1]) < target_h: lo = mid+1
        else: hi = mid-1
    return (best_f or reg.load(target_h, weight)), best_s


def _baseline_y(y1: int, y2: int, font: ImageFont.FreeTypeFont, text: str) -> int:
    ascent, descent = font.getmetrics()
    bb = font.getbbox(text); char_h = bb[3] - bb[1]
    pix_desc = int(descent * (y2-y1) / max(ascent+descent, 1)) if char_h > 0 else 2
    return y2 - pix_desc


# ── Render ─────────────────────────────────────────────────────────────

def _render_text(text: str, target_h: int, fg: tuple, weight: str) -> Image.Image:
    """8x supersample → Lanczos → RGBA at 1x."""
    scale = UPSCALE; big = max(24, int(target_h * scale * 0.75))
    font = _FontRegistry.instance().load(big, weight)
    bb = font.getbbox(text); tw, th = bb[2]-bb[0], bb[3]-bb[1]; ox, oy = bb[0], bb[1]
    pad = max(4, int(big*0.12))
    img = Image.new("RGBA", (tw+pad*2, th+pad*2), (0,0,0,0))
    ImageDraw.Draw(img).text((pad-ox, pad-oy), text, fill=fg+(255,), font=font)
    return img.resize((max(1,(tw+pad*2)//scale), max(1,(th+pad*2)//scale)), Image.LANCZOS)


# ── Texture ────────────────────────────────────────────────────────────

def _noise_std(cv_bgr: np.ndarray, x1:int, y1:int, x2:int, y2:int, band:int=30) -> float:
    h, w = cv_bgr.shape[:2]; samples = []
    for sy1,sy2,sx1,sx2 in [
        (max(0,y1-band), max(0,y1), x1,x2), (min(h,y2), min(h,y2+band), x1,x2),
        (y1,y2, max(0,x1-band), max(0,x1)), (y1,y2, min(w,x2), min(w,x2+band))
    ]:
        if sy2>sy1 and sx2>sx1 and (p:=cv_bgr[sy1:sy2, sx1:sx2].astype(float)).size>0:
            samples.append(p)
    return float(np.std(np.concatenate([s.flatten() for s in samples]))) if samples else 1.0


def _apply_texture(cv_bgr: np.ndarray, regions: list, ref: np.ndarray,
                   opacity: float = NOISE_OPACITY) -> np.ndarray:
    result = cv_bgr.astype(np.float32); h, w = cv_bgr.shape[:2]
    for x1, y1, x2, y2 in regions:
        x1, y1 = max(0,x1-4), max(0,y1-4); x2, y2 = min(w,x2+4), min(h,y2+4)
        if x2<=x1 or y2<=y1: continue
        std = _noise_std(ref, x1, y1, x2, y2)
        rh, rw = y2-y1, x2-x1
        noise = np.random.normal(0, std, (rh, rw, 3)).astype(np.float32)
        mask = cv2.GaussianBlur(np.ones((rh,rw), dtype=np.float32), (7,7), 2)[:,:,np.newaxis]
        result[y1:y2, x1:x2] = (result[y1:y2, x1:x2]*(1-mask*opacity) + noise*mask*opacity)
    return np.clip(result, 0, 255).astype(np.uint8)


# ── Verify ─────────────────────────────────────────────────────────────

def _verify(cv_bgr: np.ndarray, x1:int, y1:int, x2:int, y2:int) -> bool:
    h, w = cv_bgr.shape[:2]; x1,y1=max(8,x1),max(8,y1); x2,y2=min(w-8,x2),min(h-8,y2)
    if x2<=x1+5 or y2<=y1+5: return True
    gray = cv2.cvtColor(cv_bgr, cv2.COLOR_BGR2GRAY).astype(float)
    edge = np.abs(cv2.Sobel(gray, cv2.CV_64F, 1,0,ksize=3)) + np.abs(cv2.Sobel(gray, cv2.CV_64F, 0,1,ksize=3))
    re = float(np.mean(edge[y1:y2, x1:x2]))
    above = edge[max(0,y1-12):max(0,y1-2), x1:x2]; below = edge[min(h,y2+2):min(h,y2+12), x1:x2]
    se = float(np.mean(np.concatenate([above.flatten(), below.flatten()]))) if above.size+below.size>0 else re
    return 0.15 < re/max(se, 0.3) < 6.0


# ── Main pipeline ──────────────────────────────────────────────────────

def generate_speedtest_image(
    template_path: Path, output_path: Path,
    download_mbps: str, upload_mbps: str,
    ping_ms: str, jitter_ms: str,
    server: str = "FastIP SpeedTest",
    isp: str = "China Telecom",
    ip_addr: str = "192.168.5.10",
    location: str = "Shenzhen",
) -> Path:
    """Full pipeline: inpaint → render → texture → verify → retry. Single buffer."""

    # Load (CJK-safe)
    cv_bgr = cv2.imdecode(np.fromfile(str(template_path), np.uint8), cv2.IMREAD_COLOR)
    if cv_bgr is None:
        raise FileNotFoundError(f"Cannot read: {template_path}")
    h, w = cv_bgr.shape[:2]

    dl_int = download_mbps.split(".")[0] if "." in download_mbps else download_mbps
    dl_frac = f".{download_mbps.split('.')[1]}" if "." in download_mbps else ""

    values = {
        "download_int":  dl_int,
        "download_frac": f"{dl_frac} Mbps" if dl_frac else "Mbps",
        "upload_speed":  f"{upload_mbps} Mbps",
        "ping_value":    f"{ping_ms} ms",
        "jitter_value":  f"{jitter_ms} ms",
        "server_name":   server,
        "isp_info":      f"{isp}  {ip_addr}  {location}",
    }

    modified_regions = []

    for attempt in range(MAX_RETRIES):
        cv_work = cv_bgr.copy()
        modified_regions.clear()

        # Phase 1: Inpaint all fields
        for field in FIELDS:
            cv_work = _inpaint_field(cv_work, field)

        # Phase 2: Render + paste
        for field in FIELDS:
            if field.key not in values: continue
            text = values[field.key]

            mask = _text_mask(cv_bgr, field.x1, field.y1, field.x2, field.y2)
            ys, xs = np.where(mask > 0)
            if len(ys) < 5: continue
            char_w = int(np.max(xs) - np.min(xs) + 1)

            font, size = _find_font(char_w, field.font_size_px, field.weight)
            text_img = _render_text(text, field.font_size_px, field.fg_color, field.weight)

            # Position: center alignment
            orig_cx = (field.x1 + field.x2) // 2
            px = orig_cx - text_img.width // 2
            py = _baseline_y(field.y1, field.y2, font, text) - int(size * 0.7)
            py = max(field.y1 - 2, min(field.y2 - text_img.height + 2, py))

            # Alpha composite onto BGR
            t = np.array(text_img); ta = t[:,:,3].astype(float)/255.0; tr = t[:,:,:3].astype(float)
            tx1, ty1 = max(0,px), max(0,py); tx2, ty2 = min(w,px+text_img.width), min(h,py+text_img.height)
            for c in range(3):
                patch = cv_work[ty1:ty2, tx1:tx2, c].astype(float)
                ap = ta[ty1-py:ty1-py+(ty2-ty1), tx1-px:tx1-px+(tx2-tx1)]
                tp = tr[ty1-py:ty1-py+(ty2-ty1), tx1-px:tx1-px+(tx2-tx1), 2-c]
                cv_work[ty1:ty2, tx1:tx2, c] = np.clip(patch*(1-ap)+tp*ap, 0, 255).astype(np.uint8)
            modified_regions.append((px, py, px+text_img.width, py+text_img.height))

        # Phase 3: Texture
        cv_work = _apply_texture(cv_work, modified_regions, cv_bgr)

        # Phase 4: Verify
        all_ok = True
        for field in FIELDS:
            if field.key not in values: continue
            if not _verify(cv_work, field.x1-4, field.y1-4, field.x2+4, field.y2+4):
                all_ok = False; break
        if all_ok: break
        cv_work = _apply_texture(cv_work, modified_regions, cv_bgr, NOISE_OPACITY + attempt*0.015)

    # Save (CJK-safe)
    ok, buf = cv2.imencode(".png", cv_work)
    if ok: output_path.write_bytes(buf.tobytes())
    return output_path


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    tpl = root / "企业微信截图_17812561974493.png"
    out = root / "test_mock" / "speedtest_v7.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    generate_speedtest_image(tpl, out, "986.5", "943.2", "3", "1",
                             "FastIP SpeedTest", "China Telecom", "192.168.5.10", "Shenzhen")
    print(f"Done: {out}")
