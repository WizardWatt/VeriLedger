import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    kind: str
    confidence: float
    x: int
    y: int
    w: int
    h: int
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "kind":       self.kind,
            "confidence": round(self.confidence, 1),
            "bbox":       {"x": self.x, "y": self.y, "w": self.w, "h": self.h},
            "notes":      self.notes,
        }


@dataclass
class SealStampResult:
    overall_score: float
    seal_score: float
    stamp_score: float
    signature_score: float
    seal_found: bool
    stamp_found: bool
    signature_found: bool
    detections: List[Detection] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "overall_score":    round(self.overall_score, 1),
            "seal_score":       round(self.seal_score, 1),
            "stamp_score":      round(self.stamp_score, 1),
            "signature_score":  round(self.signature_score, 1),
            "seal_found":       self.seal_found,
            "stamp_found":      self.stamp_found,
            "signature_found":  self.signature_found,
            "detections":       [d.to_dict() for d in self.detections],
            "error":            self.error,
        }


def _empty_result(reason: str) -> SealStampResult:
    return SealStampResult(
        overall_score=0.0, seal_score=0.0, stamp_score=0.0,
        signature_score=0.0, seal_found=False, stamp_found=False,
        signature_found=False, error=reason,
    )


def _load_image(image_path: str) -> Optional[np.ndarray]:
    img = cv2.imread(image_path)
    if img is None:
        try:
            pil = Image.open(image_path).convert("RGB")
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    return img


def _in_expected_zone(cx: float, cy: float, img_h: int, img_w: int,
                      zone: str = "bottom") -> bool:
    if zone == "bottom":
        return cy > img_h * 0.60
    if zone == "bottom_half":
        return cy > img_h * 0.50
    return True


def _edge_density(gray_roi: np.ndarray) -> float:
    if gray_roi.size == 0:
        return 0.0
    edges = cv2.Canny(gray_roi, 50, 150)
    return float(edges.sum() / 255) / gray_roi.size

def _detect_seals(bgr: np.ndarray) -> Tuple[float, List[Detection]]:
    detections: List[Detection] = []
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)

    min_r = max(int(w * 0.03), 20)
    max_r = int(w * 0.15)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=int(w * 0.08),
        param1=60,
        param2=35,
        minRadius=min_r,
        maxRadius=max_r,
    )

    if circles is None:
        return 0.0, []

    circles = np.round(circles[0]).astype(int)
    best = 0.0

    for (cx, cy, r) in circles:
        cx, cy, r = int(cx), int(cy), int(r)

        x1, y1 = max(cx - r, 0), max(cy - r, 0)
        x2, y2 = min(cx + r, w), min(cy + r, h)
        roi = gray[y1:y2, x1:x2]

        density = _edge_density(roi)

        conf = min(density * 350, 80.0)

        if _in_expected_zone(cx, cy, h, w, "bottom"):
            conf = min(conf + 15, 100.0)

        if r > int(w * 0.05):
            conf = min(conf + 5, 100.0)

        if conf >= 25:
            det = Detection(
                kind="seal", confidence=conf,
                x=x1, y=y1, w=x2 - x1, h=y2 - y1,
                notes=f"circle r={r}px edge_density={density:.3f}",
            )
            detections.append(det)
            best = max(best, conf)

    return best, detections


def _detect_stamps(bgr: np.ndarray) -> Tuple[float, List[Detection]]:
    detections: List[Detection] = []
    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    red_lo1 = cv2.inRange(hsv, np.array([0,  80,  80]), np.array([10,  255, 255]))
    red_lo2 = cv2.inRange(hsv, np.array([160, 80,  80]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(red_lo1, red_lo2)

    blue_mask = cv2.inRange(hsv, np.array([100, 60, 60]), np.array([130, 255, 255]))

    purple_mask = cv2.inRange(hsv, np.array([130, 50, 50]), np.array([160, 255, 255]))

    combined = cv2.bitwise_or(red_mask, cv2.bitwise_or(blue_mask, purple_mask))

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    min_area = (w * h) * 0.001
    best = 0.0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        cx, cy = x + bw // 2, y + bh // 2

        aspect = bw / bh if bh > 0 else 999
        if aspect > 8 or aspect < 0.125:
            continue

        roi_gray = cv2.cvtColor(bgr[y:y+bh, x:x+bw], cv2.COLOR_BGR2GRAY)
        density = _edge_density(roi_gray)

        area_norm = min(area / (w * h * 0.05), 1.0)
        conf = area_norm * 40 + density * 200
        conf = min(conf, 80.0)

        if _in_expected_zone(cx, cy, h, w, "bottom_half"):
            conf = min(conf + 15, 100.0)

        if conf >= 25:
            det = Detection(
                kind="stamp", confidence=conf,
                x=x, y=y, w=bw, h=bh,
                notes=f"ink_blob area={int(area)}px² edge_density={density:.3f}",
            )
            detections.append(det)
            best = max(best, conf)

    return best, detections


def _detect_signatures(bgr: np.ndarray) -> Tuple[float, List[Detection]]:
    detections: List[Detection] = []
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=15, C=8,
    )

    roi_top = h // 2
    thresh_bottom = thresh[roi_top:, :]

    contours, _ = cv2.findContours(thresh_bottom, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    min_area = w * h * 0.0005
    max_area = w * h * 0.15
    best = 0.0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        y += roi_top

        aspect = bw / bh if bh > 0 else 0
        if not (1.0 < aspect < 10.0):
            continue

        perimeter = cv2.arcLength(cnt, False)
        if perimeter == 0:
            continue
        complexity = (perimeter ** 2) / (area + 1)

        if complexity < 20:
            continue

        norm_complexity = min(complexity / 500.0, 1.0)

        aspect_score = 1.0 if 2.0 <= aspect <= 6.0 else 0.6

        conf = norm_complexity * 60 * aspect_score
        conf = min(conf + 10, 100.0)

        if conf >= 25:
            det = Detection(
                kind="signature", confidence=conf,
                x=x, y=y, w=bw, h=bh,
                notes=f"complexity={complexity:.1f} aspect={aspect:.2f}",
            )
            detections.append(det)
            best = max(best, conf)

    return best, detections


def _ensure_jpeg(image_path: str) -> Tuple[str, bool]:
    suffix = Path(image_path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return image_path, False
    try:
        img = Image.open(image_path).convert("RGB")
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp = f.name
        img.save(tmp, "JPEG", quality=95)
        return tmp, True
    except Exception as exc:
        logger.warning(f"Image conversion for seal analysis failed: {exc}")
        return image_path, False


def _pdf_to_image(pdf_path: str) -> Optional[str]:
    try:
        from pdf2image import convert_from_path
        from config import POPPLER_PATH
        pages = convert_from_path(pdf_path, first_page=1, last_page=1,
                                  dpi=150, poppler_path=POPPLER_PATH)
        if not pages:
            return None
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp = f.name
        pages[0].save(tmp, "JPEG", quality=95)
        return tmp
    except Exception as exc:
        logger.warning(f"PDF→image for seal analysis failed: {exc}")
        return None


def run_seal_stamp_analysis(image_path: str) -> SealStampResult:
    path = Path(image_path)
    if not path.exists():
        return _empty_result(f"File not found: {image_path}")

    suffix = path.suffix.lower()
    tmp_to_cleanup: Optional[str] = None

    try:
        if suffix == ".pdf":
            working = _pdf_to_image(image_path)
            if working is None:
                return _empty_result("Could not convert PDF to image.")
            tmp_to_cleanup = working
        elif suffix in {".png", ".bmp", ".tiff", ".tif"}:
            working, was_temp = _ensure_jpeg(image_path)
            if was_temp:
                tmp_to_cleanup = working
        elif suffix in {".jpg", ".jpeg"}:
            working = image_path
        else:
            return _empty_result(f"Unsupported file type: {suffix}")

        bgr = _load_image(working)
        if bgr is None:
            return _empty_result(f"Could not load image: {working}")

        seal_score,      seal_dets      = _detect_seals(bgr)
        stamp_score,     stamp_dets     = _detect_stamps(bgr)
        signature_score, signature_dets = _detect_signatures(bgr)

        overall = (
            seal_score      * 0.40 +
            stamp_score     * 0.35 +
            signature_score * 0.25
        )
        overall = round(min(overall, 100.0), 1)

        all_detections = seal_dets + stamp_dets + signature_dets

        logger.info(
            f"SealStamp | {path.name} overall={overall} "
            f"seal={seal_score:.1f} stamp={stamp_score:.1f} "
            f"sig={signature_score:.1f} detections={len(all_detections)}"
        )

        return SealStampResult(
            overall_score=overall,
            seal_score=round(seal_score, 1),
            stamp_score=round(stamp_score, 1),
            signature_score=round(signature_score, 1),
            seal_found=seal_score > 40,
            stamp_found=stamp_score > 40,
            signature_found=signature_score > 40,
            detections=all_detections,
        )

    except Exception as exc:
        logger.error(f"Seal/stamp analysis failed: {exc}", exc_info=True)
        return _empty_result(str(exc))

    finally:
        if tmp_to_cleanup:
            try:
                Path(tmp_to_cleanup).unlink()
            except Exception:
                pass
