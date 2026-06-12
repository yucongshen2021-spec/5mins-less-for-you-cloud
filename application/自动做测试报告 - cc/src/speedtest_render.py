"""Speedtest screenshot parameter replacement — component-level rebuilder."""
from __future__ import annotations

import io, math, os, sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import cv2
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
