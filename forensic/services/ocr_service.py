import logging
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import json

import pytesseract
import cv2
import numpy as np
from PIL import Image

from config import (
    OCR_PSM_MODE,
    OCR_LANGUAGE,
    CONFIDENCE_THRESHOLD,
    OUTPUTS_DIR,
    SAVE_OUTPUT_TO_DISK,
    OUTPUT_FORMAT,
)
from services.image_preprocessing import ImagePreprocessor
from services.pdf_service import PDFService
from models.response_models import (
    ConfidenceMetrics,
    MetadataInfo,
    PageOCRResult,
    DocumentType,
    StructuredOCROutput,
    create_success_response,
)

logger = logging.getLogger(__name__)


class OCRService:
    @staticmethod
    def check_tesseract_installation() -> bool:
        try:
            pytesseract.get_tesseract_version()
            logger.info("Tesseract OCR is installed and available")
            return True
        except Exception as e:
            logger.error(f"Tesseract not available: {str(e)}")
            return False

    @staticmethod
    def extract_text_with_confidence(image: np.ndarray) -> Tuple[str, float, int]:
        try:
            ocr_data = pytesseract.image_to_data(
                image,
                lang=OCR_LANGUAGE,
                config=f"--psm {OCR_PSM_MODE}",
                output_type=pytesseract.Output.DICT,
            )

            confidences = []
            words = []

            for i, word in enumerate(ocr_data["text"]):
                if word.strip():
                    confidence = float(ocr_data["conf"][i])
                    if confidence > 0:
                        confidences.append(confidence)
                        words.append(word)

            word_count = len(words)
            avg_confidence = (
                sum(confidences) / len(confidences) if confidences else 0
            )

            text = pytesseract.image_to_string(
                image,
                lang=OCR_LANGUAGE,
                config=f"--psm {OCR_PSM_MODE}",
            )

            logger.debug(
                f"OCR complete: {word_count} words, "
                f"{avg_confidence:.2f}% confidence"
            )

            return text, avg_confidence, word_count

        except Exception as e:
            logger.error(f"Error during OCR: {str(e)}")
            return "", 0.0, 0

    @staticmethod
    def extract_confidence_metrics(image: np.ndarray) -> ConfidenceMetrics:
        try:
            ocr_data = pytesseract.image_to_data(
                image,
                lang=OCR_LANGUAGE,
                config=f"--psm {OCR_PSM_MODE}",
                output_type=pytesseract.Output.DICT,
            )

            confidences = []
            high_confidence_count = 0
            low_confidence_count = 0

            for i, word in enumerate(ocr_data["text"]):
                if word.strip():
                    confidence = float(ocr_data["conf"][i])
                    if confidence > 0:
                        confidences.append(confidence)
                        if confidence > 80:
                            high_confidence_count += 1
                        elif confidence < 50:
                            low_confidence_count += 1

            avg_confidence = (
                sum(confidences) / len(confidences) if confidences else 0
            )
            word_count = len(confidences)

            return ConfidenceMetrics(
                average_confidence=avg_confidence,
                word_count=word_count,
                high_confidence_words=high_confidence_count,
                low_confidence_words=low_confidence_count,
            )

        except Exception as e:
            logger.error(f"Error extracting confidence metrics: {str(e)}")
            return ConfidenceMetrics(
                average_confidence=0.0,
                word_count=0,
            )

    @staticmethod
    def process_image(
        image_path: str,
        preprocess: bool = True,
    ) -> Tuple[str, ConfidenceMetrics, float]:
        start_time = time.time()
        
        try:
            logger.info(f"Processing image: {image_path}")

            if preprocess:
                try:
                    processed_image, pipeline = (
                        ImagePreprocessor.preprocess_for_ocr(image_path)
                    )
                    logger.info(f"Applied preprocessing: {pipeline}")
                except Exception as e:
                    logger.warning(f"Preprocessing failed, using original: {str(e)}")
                    processed_image = cv2.imread(image_path)
            else:
                processed_image = cv2.imread(image_path)

            if processed_image is None:
                raise ValueError("Failed to load image")

            text, _, _ = OCRService.extract_text_with_confidence(processed_image)
            confidence = OCRService.extract_confidence_metrics(processed_image)

            processing_time = time.time() - start_time
            logger.info(f"Image OCR complete in {processing_time:.2f}s")

            return text, confidence, processing_time

        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
            raise

    @staticmethod
    def process_pdf(pdf_path: str) -> Tuple[str, List[PageOCRResult], float]:
        start_time = time.time()
        
        try:
            logger.info(f"Processing PDF: {pdf_path}")

            images = PDFService.convert_pdf_to_images(pdf_path)
            logger.info(f"Converted PDF to {len(images)} images")

            page_results: List[PageOCRResult] = []
            combined_text_parts = []

            for page_num, image in enumerate(images, 1):
                logger.debug(f"Processing PDF page {page_num}/{len(images)}")

                try:
                    pass
                except Exception as e:
                    logger.warning(f"Preprocessing failed for page {page_num}: {e}")

                text, avg_confidence, word_count = (
                    OCRService.extract_text_with_confidence(image)
                )
                confidence = OCRService.extract_confidence_metrics(image)

                page_result = PageOCRResult(
                    page_number=page_num,
                    text=text,
                    confidence=confidence,
                    char_count=len(text),
                )
                page_results.append(page_result)
                combined_text_parts.append(f"--- PAGE {page_num} ---\n{text}")

                logger.debug(
                    f"Page {page_num}: {word_count} words, "
                    f"{avg_confidence:.2f}% confidence"
                )

            combined_text = "\n\n".join(combined_text_parts)

            processing_time = time.time() - start_time
            logger.info(f"PDF OCR complete in {processing_time:.2f}s ({len(images)} pages)")

            return combined_text, page_results, processing_time

        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            raise

    @staticmethod
    def save_ocr_output(
        filename: str,
        output_data: Dict,
        output_dir: Path = OUTPUTS_DIR,
    ) -> Path:
        try:
            output_dir.mkdir(exist_ok=True)
            
            extension = f".{OUTPUT_FORMAT}"
            output_path = output_dir / f"{filename}{extension}"

            if OUTPUT_FORMAT == "json":
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)
            else:
                with open(output_path, "w", encoding="utf-8") as f:
                    if isinstance(output_data, dict):
                        f.write(output_data.get("extracted_text", ""))
                    else:
                        f.write(str(output_data))

            logger.info(f"Saved OCR output to {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error saving OCR output: {str(e)}")
            return None

    @staticmethod
    def get_structured_ocr_output(
        extracted_text: str,
        confidence: ConfidenceMetrics,
        metadata: MetadataInfo,
        pages: Optional[List[PageOCRResult]] = None,
    ) -> StructuredOCROutput:
        output = StructuredOCROutput(
            raw_text=extracted_text,
            confidence=confidence,
            metadata=metadata,
            pages=pages,
        )
        logger.info("Created structured OCR output for downstream modules")
        return output
