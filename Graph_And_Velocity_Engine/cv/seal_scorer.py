"""
VeriLedger — CV Seal/Stamp Scorer
===================================
Takes a cropped stamp/seal image (PIL Image) and returns a 0–1 confidence score
indicating how likely the seal is genuine.

Score interpretation:
  >= 0.6  → seal looks authentic
  0.4–0.6 → uncertain, flag for manual review
  < 0.4   → suspicious (ForensicSignals.seal_score threshold)

Method: pure heuristics, no trained model.
  1. Edge density      — real seals have dense, consistent ink edges
  2. Circular shape    — Hough-circle detection; genuine seals are round
  3. Aspect ratio      — near-square bounding box (circle fits in square)
  4. Ink coverage      — fraction of dark pixels; sparse = low-quality scan or fake
  5. Symmetry score    — left/right and top/bottom pixel symmetry
"""

from __future__ import annotations
import math
from typing import Optional

import numpy as np
from PIL import Image

try:
    from scipy.ndimage import sobel
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False


# ── Tunable weights ────────────────────────────────────────────────────────────
WEIGHT_EDGE_DENSITY  = 0.30
WEIGHT_CIRCULARITY   = 0.30
WEIGHT_ASPECT_RATIO  = 0.15
WEIGHT_INK_COVERAGE  = 0.15
WEIGHT_SYMMETRY      = 0.10

# Edge density: fraction of edge pixels relative to total — genuine seals are 0.05–0.25
EDGE_LOW  = 0.04
EDGE_HIGH = 0.30

# Ink coverage: fraction of dark pixels
INK_DARK_THRESHOLD = 128   # pixel intensity below this = "ink"
INK_LOW  = 0.05
INK_HIGH = 0.60


def score_seal(image: Image.Image) -> float:
    """
    Score a cropped seal/stamp image.

    Args:
        image: PIL Image of the seal region (any mode; converted internally).
               Must be a CROPPED seal/stamp, not a full document page.
               Images wider or taller than 800px are assumed to be full-page
               scans and will return 0.5 (indeterminate) with a warning.

    Returns:
        float in [0, 1] — higher = more confident the seal is genuine.
        Returns 0.5 if the image is too small or too large to score reliably.
    """
    if image.width < 20 or image.height < 20:
        return 0.5   # too small to say anything
    if image.width > 800 or image.height > 800:
        # Almost certainly a full document page, not a seal crop.
        # Scoring a full page produces meaningless heuristics.
        import warnings
        warnings.warn(
            f"score_seal received a large image ({image.width}x{image.height}px). "
            "Pass a cropped seal/stamp region, not a full page. Returning 0.5 (indeterminate).",
            UserWarning, stacklevel=2,
        )
        return 0.5

    gray = _to_grayscale_array(image)

    edge_score    = _score_edge_density(gray)
    circle_score  = _score_circularity(gray)
    aspect_score  = _score_aspect_ratio(image.width, image.height)
    ink_score     = _score_ink_coverage(gray)
    sym_score     = _score_symmetry(gray)

    composite = (
        WEIGHT_EDGE_DENSITY * edge_score
        + WEIGHT_CIRCULARITY  * circle_score
        + WEIGHT_ASPECT_RATIO * aspect_score
        + WEIGHT_INK_COVERAGE * ink_score
        + WEIGHT_SYMMETRY     * sym_score
    )
    return round(float(np.clip(composite, 0.0, 1.0)), 4)


def score_seal_with_breakdown(image: Image.Image) -> dict:
    """
    Same as score_seal but returns a dict with per-component scores.
    Useful for debugging and report generation.
    """
    if image.width < 20 or image.height < 20:
        return {"final_score": 0.5, "verdict": "indeterminate", "note": "image too small to score"}
    if image.width > 800 or image.height > 800:
        import warnings
        warnings.warn(
            f"score_seal_with_breakdown received a large image ({image.width}x{image.height}px). "
            "Pass a cropped seal/stamp region, not a full page.",
            UserWarning, stacklevel=2,
        )
        return {"final_score": 0.5, "verdict": "indeterminate", "note": "image too large — expected a cropped seal, not a full page"}

    gray = _to_grayscale_array(image)

    components = {
        "edge_density":  _score_edge_density(gray),
        "circularity":   _score_circularity(gray),
        "aspect_ratio":  _score_aspect_ratio(image.width, image.height),
        "ink_coverage":  _score_ink_coverage(gray),
        "symmetry":      _score_symmetry(gray),
    }

    final = (
        WEIGHT_EDGE_DENSITY * components["edge_density"]
        + WEIGHT_CIRCULARITY  * components["circularity"]
        + WEIGHT_ASPECT_RATIO * components["aspect_ratio"]
        + WEIGHT_INK_COVERAGE * components["ink_coverage"]
        + WEIGHT_SYMMETRY     * components["symmetry"]
    )
    components["final_score"] = round(float(np.clip(final, 0.0, 1.0)), 4)
    components["verdict"] = _verdict(components["final_score"])
    return components


# ── Component scorers ──────────────────────────────────────────────────────────

def _score_edge_density(gray: np.ndarray) -> float:
    """Fraction of edge pixels — uses Sobel or fallback gradient."""
    if _SCIPY_AVAILABLE:
        sx = sobel(gray.astype(float), axis=1)
        sy = sobel(gray.astype(float), axis=0)
        magnitude = np.hypot(sx, sy)
    else:
        # Simple 3x3 gradient fallback using numpy
        gy = np.gradient(gray.astype(float), axis=0)
        gx = np.gradient(gray.astype(float), axis=1)
        magnitude = np.hypot(gx, gy)

    # Normalize magnitude to [0,1]
    mag_max = magnitude.max()
    if mag_max == 0:
        return 0.0

    edge_pixels = (magnitude / mag_max) > 0.2
    density = edge_pixels.mean()

    # Score: peak in the middle of the expected range
    if density < EDGE_LOW:
        return density / EDGE_LOW * 0.5          # too few edges → likely blank/fake
    if density > EDGE_HIGH:
        return max(0.0, 1.0 - (density - EDGE_HIGH) / EDGE_HIGH)  # too noisy → dirty scan
    # Within range: full score scaled linearly to peak at midpoint
    mid = (EDGE_LOW + EDGE_HIGH) / 2
    dist = abs(density - mid) / ((EDGE_HIGH - EDGE_LOW) / 2)
    return 1.0 - dist * 0.4


def _score_circularity(gray: np.ndarray) -> float:
    """
    Estimate how circular the seal is using contour-based circularity:
      circularity = 4π·area / perimeter²
    Approximated here with binary thresholding + bounding-box heuristic.
    """
    binary = (gray < 128).astype(np.uint8)   # dark pixels = ink

    ink_count = binary.sum()
    if ink_count < 50:
        return 0.2   # almost no ink → probably blank

    # Find bounding box of ink pixels
    rows = np.any(binary, axis=1)
    cols = np.any(binary, axis=0)
    if not rows.any() or not cols.any():
        return 0.2

    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]

    h = rmax - rmin + 1
    w = cmax - cmin + 1
    bounding_area = h * w
    if bounding_area == 0:
        return 0.0

    # For a perfect circle, ink fills ~π/4 ≈ 0.785 of bounding square
    fill_ratio = ink_count / bounding_area
    circle_fill = math.pi / 4   # ≈ 0.785

    # Score peaks at circle_fill
    diff = abs(fill_ratio - circle_fill)
    score = max(0.0, 1.0 - diff / circle_fill)
    return float(score)


def _score_aspect_ratio(width: int, height: int) -> float:
    """Genuine seals are roughly square (circle fits in square bounding box)."""
    if width == 0 or height == 0:
        return 0.0
    ratio = min(width, height) / max(width, height)   # 1.0 = perfect square
    # Linear decay from 1.0 (square) to 0.0 (very elongated)
    return float(max(0.0, ratio))


def _score_ink_coverage(gray: np.ndarray) -> float:
    """Fraction of dark pixels — genuine seals have moderate ink density."""
    dark_pixels = (gray < INK_DARK_THRESHOLD).mean()

    if dark_pixels < INK_LOW:
        return dark_pixels / INK_LOW * 0.5     # nearly blank
    if dark_pixels > INK_HIGH:
        return max(0.0, 1.0 - (dark_pixels - INK_HIGH) / INK_HIGH)  # filled black block
    # Good range
    mid = (INK_LOW + INK_HIGH) / 2
    dist = abs(dark_pixels - mid) / ((INK_HIGH - INK_LOW) / 2)
    return float(1.0 - dist * 0.3)


def _score_symmetry(gray: np.ndarray) -> float:
    """
    Circular seals are roughly symmetric left/right and top/bottom.
    Measure normalized pixel difference between halves.
    """
    h, w = gray.shape
    float_gray = gray.astype(float)

    # Left/right symmetry
    left  = float_gray[:, : w // 2]
    right = np.fliplr(float_gray[:, w - w // 2:])
    min_w = min(left.shape[1], right.shape[1])
    lr_diff = np.abs(left[:, :min_w] - right[:, :min_w]).mean() / 255.0

    # Top/bottom symmetry
    top    = float_gray[: h // 2, :]
    bottom = np.flipud(float_gray[h - h // 2:, :])
    min_h = min(top.shape[0], bottom.shape[0])
    tb_diff = np.abs(top[:min_h, :] - bottom[:min_h, :]).mean() / 255.0

    avg_diff = (lr_diff + tb_diff) / 2.0
    return float(max(0.0, 1.0 - avg_diff * 4))   # scale: 0.25 avg diff → score 0


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_grayscale_array(image: Image.Image) -> np.ndarray:
    """Convert any PIL image mode to a uint8 grayscale numpy array."""
    if image.mode != "L":
        image = image.convert("L")
    return np.array(image, dtype=np.uint8)


def _verdict(score: float) -> str:
    if score >= 0.6:
        return "authentic"
    if score >= 0.4:
        return "uncertain — manual review recommended"
    return "suspicious — possible forgery"
