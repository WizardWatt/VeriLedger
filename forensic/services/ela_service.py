import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_RESAVE_QUALITY = 90

_AMP_FACTOR = 10

_HOTSPOT_THRESHOLD = 25

_MEAN_CEIL  = 25.0
_STD_CEIL   = 30.0
_RATIO_CEIL = 0.15


@dataclass
class ELAResult:
    ela_score: float
    max_pixel_error: float
    mean_pixel_error: float
    std_pixel_error: float
    suspicious_region_ratio: float
    amplified_ela_path: Optional[str] = None
    error: Optional[str] = None
    source_is_pdf: bool = False

    def to_dict(self) -> dict:
        return {
            "ela_score":               round(self.ela_score, 2),
            "max_pixel_error":         round(self.max_pixel_error, 2),
            "mean_pixel_error":        round(self.mean_pixel_error, 2),
            "std_pixel_error":         round(self.std_pixel_error, 2),
            "suspicious_region_ratio": round(self.suspicious_region_ratio, 4),
            "amplified_ela_path":      self.amplified_ela_path,
            "error":                   self.error,
            "source_is_pdf":           self.source_is_pdf,
        }


def _failed(reason: str) -> ELAResult:
    return ELAResult(0.0, 0.0, 0.0, 0.0, 0.0, error=reason)


def _to_jpeg(source_path: str) -> Optional[str]:
    try:
        img = Image.open(source_path).convert("RGB")
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp_path = f.name
        img.save(tmp_path, "JPEG", quality=95)
        logger.debug(f"PNG→JPEG conversion: {source_path} → {tmp_path}")
        return tmp_path
    except Exception as exc:
        logger.warning(f"PNG→JPEG conversion failed for {source_path}: {exc}")
        return None



def _pdf_to_image(pdf_path: str) -> Optional[str]:
    try:
        from pdf2image import convert_from_path
        from config import POPPLER_PATH

        pages = convert_from_path(
            pdf_path,
            first_page=1,
            last_page=1,
            dpi=150,
            poppler_path=POPPLER_PATH,
        )
        if not pages:
            return None

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp_path = f.name
        pages[0].save(tmp_path, "JPEG", quality=95)
        return tmp_path

    except Exception as exc:
        logger.warning(f"PDF→image for ELA failed: {exc}")
        return None


def _ela_on_jpeg(jpeg_path: str) -> ELAResult:
    try:
        original = cv2.imread(jpeg_path)
        if original is None:
            return _failed(f"cv2 could not read: {jpeg_path}")

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            resave_path = f.name

        cv2.imwrite(resave_path, original, [cv2.IMWRITE_JPEG_QUALITY, _RESAVE_QUALITY])
        resaved = cv2.imread(resave_path)

        try:
            Path(resave_path).unlink()
        except Exception:
            pass

        if resaved is None or resaved.shape != original.shape:
            return _failed("Re-saved image unreadable or mismatched shape.")

        diff = cv2.absdiff(original.astype(np.float32),
                           resaved.astype(np.float32))
        diff_single = diff.max(axis=2)

        max_err  = float(diff_single.max())
        mean_err = float(diff_single.mean())
        std_err  = float(diff_single.std())
        amplified = np.clip(diff_single * _AMP_FACTOR, 0, 255).astype(np.uint8)
        suspicious_pixels = int((amplified > _HOTSPOT_THRESHOLD).sum())
        suspicious_ratio  = suspicious_pixels / amplified.size

        norm_mean  = min(mean_err / _MEAN_CEIL,   1.0)
        norm_std   = min(std_err  / _STD_CEIL,    1.0)
        norm_ratio = min(suspicious_ratio / _RATIO_CEIL, 1.0)

        ela_score = (norm_mean * 0.25 + norm_std * 0.45 + norm_ratio * 0.30) * 100.0
        ela_score = round(min(ela_score, 100.0), 2)

        logger.info(
            f"ELA | {Path(jpeg_path).name} "
            f"score={ela_score} mean={mean_err:.2f} std={std_err:.2f} "
            f"suspicious_ratio={suspicious_ratio:.4f}"
        )

        return ELAResult(
            ela_score=ela_score,
            max_pixel_error=max_err,
            mean_pixel_error=mean_err,
            std_pixel_error=std_err,
            suspicious_region_ratio=suspicious_ratio,
        )

    except Exception as exc:
        logger.error(f"ELA failed for {jpeg_path}: {exc}", exc_info=True)
        return _failed(str(exc))


def run_ela(image_path: str) -> ELAResult:
    path = Path(image_path)

    if not path.exists():
        return _failed(f"File not found: {image_path}")

    suffix = path.suffix.lower()

    if suffix in {".jpg", ".jpeg"}:
        return _ela_on_jpeg(image_path)

    if suffix in {".png", ".bmp", ".tiff", ".tif"}:
        tmp_jpeg = _to_jpeg(image_path)
        if tmp_jpeg is None:
            return _failed(f"Could not convert {suffix} to JPEG for ELA.")
        result = _ela_on_jpeg(tmp_jpeg)
        try:
            Path(tmp_jpeg).unlink()
        except Exception:
            pass
        return result

    if suffix == ".pdf":
        tmp_jpeg = _pdf_to_image(image_path)
        if tmp_jpeg is None:
            return _failed("Could not convert PDF first page to image for ELA.")
        result = _ela_on_jpeg(tmp_jpeg)
        result.source_is_pdf = True
        try:
            Path(tmp_jpeg).unlink()
        except Exception:
            pass
    return result

    return _failed(f"Unsupported file type for ELA: {suffix}")
