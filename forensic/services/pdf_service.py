import logging
from typing import List, Tuple
from pathlib import Path
from pdf2image.pdf2image import pdfinfo_from_path

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None

import cv2
import numpy as np

from config import PDF_DPI, MAX_PDF_PAGES, POPPLER_PATH

logger = logging.getLogger(__name__)


class PDFService:
    @staticmethod
    def get_pdf_page_count(pdf_path: str) -> int:
        info = pdfinfo_from_path(pdf_path, poppler_path=POPPLER_PATH or None)
        return int(info["Pages"])

    @staticmethod
    def convert_pdf_to_images(pdf_path: str, dpi: int = PDF_DPI) -> List[np.ndarray]:
        try:
            if convert_from_path is None:
                raise ImportError("pdf2image not installed")

            logger.info(f"Converting PDF to images at {dpi} DPI: {Path(pdf_path).name}")

            page_count = PDFService.get_pdf_page_count(pdf_path)
            
            if page_count > MAX_PDF_PAGES:
                logger.warning(
                    f"PDF has {page_count} pages, limiting to {MAX_PDF_PAGES}"
                )
                page_count = MAX_PDF_PAGES

            pil_images = convert_from_path(
                pdf_path,
                dpi=dpi,
                last_page=page_count,
                poppler_path=POPPLER_PATH,
            )

            cv2_images = []
            for i, pil_image in enumerate(pil_images, 1):
                cv2_image = cv2.cvtColor(
                    np.array(pil_image),
                    cv2.COLOR_RGB2BGR,
                )
                cv2_images.append(cv2_image)
                logger.debug(f"Converted PDF page {i}/{len(pil_images)}")

            logger.info(f"Successfully converted {len(cv2_images)} pages from PDF")
            return cv2_images

        except Exception as e:
            logger.error(f"Error converting PDF to images: {str(e)}")
            raise ValueError(f"Failed to convert PDF: {str(e)}")

    @staticmethod
    def extract_pdf_metadata(pdf_path: str) -> Tuple[int, int]:
        try:
            file_size = Path(pdf_path).stat().st_size
            page_count = PDFService.get_pdf_page_count(pdf_path)
            
            logger.debug(f"PDF metadata: {page_count} pages, {file_size} bytes")
            return page_count, file_size

        except Exception as e:
            logger.error(f"Error extracting PDF metadata: {str(e)}")
            return 0, 0
