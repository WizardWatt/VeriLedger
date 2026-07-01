import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FontResult:
    font_inconsistency: bool
    inconsistency_score: float
    fonts_found: List[str] = field(default_factory=list)
    unique_font_count: int = 0
    flags: List[str] = field(default_factory=list)
    method: str = "unknown"
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "font_inconsistency":  self.font_inconsistency,
            "inconsistency_score": round(self.inconsistency_score, 1),
            "fonts_found":         self.fonts_found,
            "unique_font_count":   self.unique_font_count,
            "flags":               self.flags,
            "method":              self.method,
            "error":               self.error,
        }


def _clean_result(score: float = 0.0) -> FontResult:
    return FontResult(
        font_inconsistency=False,
        inconsistency_score=score,
        method="none",
    )


def _error_result(msg: str) -> FontResult:
    return FontResult(
        font_inconsistency=False,
        inconsistency_score=0.0,
        error=msg,
        method="error",
    )


def _normalise_font_family(raw_name: str) -> str:
    name = re.sub(r"[-,+]?(Bold|Italic|Regular|Light|Medium|Heavy|"
                  r"MT|PS|BoldMT|ItalicMT|BoldItalicMT|Narrow|"
                  r"Condensed|Extended|Oblique|Slanted).*$",
                  "", raw_name, flags=re.IGNORECASE)
    name = re.sub(r"^[A-Z]{6}\+", "", name)
    return name.strip("-,").strip()


def _analyse_pdf_fonts(pdf_path: str) -> FontResult:
    try:
        import fitz
    except ImportError:
        return _error_result(
            "PyMuPDF (fitz) not installed. Run: pip install pymupdf --break-system-packages"
        )

    try:
        doc = fitz.open(pdf_path)
        flags: List[str] = []

        page_fonts: Dict[int, Set[str]] = {}
        all_families: Set[str] = set()

        for page_num in range(len(doc)):
            page = doc[page_num]
            font_list = page.get_fonts(full=True)
            families_on_page: Set[str] = set()

            for font in font_list:
                raw_name = font[3] or font[4] or ""
                if not raw_name:
                    continue
                family = _normalise_font_family(raw_name)
                if family:
                    families_on_page.add(family)
                    all_families.add(family)

            page_fonts[page_num] = families_on_page

        doc.close()

        unique_count = len(all_families)
        all_families_list = sorted(all_families)

        score = 0.0

        if unique_count > 4:
            score += 60
            flags.append(f"{unique_count} distinct font families found (expected ≤2 for official docs)")
        elif unique_count == 4:
            score += 40
            flags.append(f"{unique_count} distinct font families found")
        elif unique_count == 3:
            score += 20
            flags.append(f"{unique_count} distinct font families found")

        if len(page_fonts) > 1:
            all_page_families = list(page_fonts.values())
            global_common = set.intersection(*all_page_families) if all_page_families else set()

            for page_num, families in page_fonts.items():
                page_only = families - global_common
                if page_only:
                    score += 15
                    flags.append(
                        f"Page {page_num + 1} has unique fonts not seen on other pages: "
                        + ", ".join(sorted(page_only))
                    )

        suspicious_fonts = {"courier", "typewriter", "ocr", "handwriting"}
        for fam in all_families:
            if any(s in fam.lower() for s in suspicious_fonts):
                score += 10
                flags.append(f"Unusual font for an official document: '{fam}'")

        score = min(score, 100.0)

        return FontResult(
            font_inconsistency=score > 30,
            inconsistency_score=round(score, 1),
            fonts_found=all_families_list,
            unique_font_count=unique_count,
            flags=flags,
            method="pdf_fitz",
        )

    except Exception as exc:
        logger.error(f"PDF font analysis failed: {exc}", exc_info=True)
        return _error_result(str(exc))


def _analyse_image_fonts(image_path: str) -> FontResult:
    flags: List[str] = []

    try:
        bgr = cv2.imread(image_path)
        if bgr is None:
            return _error_result(f"Could not load image: {image_path}")

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        thresh = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            blockSize=15, C=8,
        )

        dist = cv2.distanceTransform(thresh, cv2.DIST_L2, 5)
        grid_rows, grid_cols = 6, 4
        cell_h = h // grid_rows
        cell_w = w // grid_cols

        stroke_widths: List[float] = []

        for r in range(grid_rows):
            for c in range(grid_cols):
                y1, y2 = r * cell_h, (r + 1) * cell_h
                x1, x2 = c * cell_w, (c + 1) * cell_w

                cell_thresh = thresh[y1:y2, x1:x2]
                cell_dist   = dist[y1:y2, x1:x2]

                ink_fraction = cell_thresh.sum() / (255 * cell_thresh.size)
                if ink_fraction < 0.02:
                    continue

                nonzero_dist = cell_dist[cell_dist > 0]
                if len(nonzero_dist) < 50:
                    continue
                median_sw = float(np.median(nonzero_dist)) * 2.0
                stroke_widths.append(median_sw)

        if len(stroke_widths) < 3:
            return _clean_result(0.0)

        sw_array = np.array(stroke_widths)
        sw_mean = float(sw_array.mean())
        sw_std  = float(sw_array.std())

        cv_ratio = sw_std / sw_mean if sw_mean > 0 else 0.0

        if cv_ratio > 0.50:
            score = 80.0
            flags.append(
                f"Very high stroke width variance (CV={cv_ratio:.2f}) — "
                "strongly suggests mixed fonts from different sources"
            )
        elif cv_ratio > 0.35:
            score = 50.0
            flags.append(
                f"Elevated stroke width variance (CV={cv_ratio:.2f}) — "
                "possible font mixing"
            )
        elif cv_ratio > 0.25:
            score = 25.0
            flags.append(
                f"Mild stroke width variance (CV={cv_ratio:.2f})"
            )
        else:
            score = 0.0

        return FontResult(
            font_inconsistency=score > 30,
            inconsistency_score=round(score, 1),
            fonts_found=[],
            unique_font_count=0,
            flags=flags,
            method="image_swt",
        )

    except Exception as exc:
        logger.error(f"Image font analysis failed: {exc}", exc_info=True)
        return _error_result(str(exc))


def _pdf_to_image_path(pdf_path: str) -> Optional[str]:
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
    except Exception:
        return None


def run_font_analysis(file_path: str, ocr_text: str = "") -> FontResult:
    path = Path(file_path)
    if not path.exists():
        return _error_result(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        result = _analyse_pdf_fonts(file_path)
        if result.error and "PyMuPDF" in (result.error or ""):
            logger.info("PyMuPDF unavailable, falling back to image SWT for PDF")
            tmp = _pdf_to_image_path(file_path)
            if tmp:
                result = _analyse_image_fonts(tmp)
                try:
                    Path(tmp).unlink()
                except Exception:
                    pass
        return result

    elif suffix in {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}:
        return _analyse_image_fonts(file_path)

    return _error_result(f"Unsupported file type for font analysis: {suffix}")
