import logging
import time
from pathlib import Path
from typing import Optional, Tuple
from services.ela_service import run_ela
from services.seal_stamp_service import run_seal_stamp_analysis
from services.font_service        import run_font_analysis
from services.llm_service import synthesize_risk_report

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from werkzeug.exceptions import BadRequest

from config import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    UPLOADS_DIR,
    SAVE_OUTPUT_TO_DISK,
)
from models.response_models import (
    DocumentType,
    MetadataInfo,
    create_error_response,
    create_success_response,
)
from models.extracted_models import SharedEntityFields
from services.extraction_service import ExtractionService
from services.ocr_service import OCRService
from services.pdf_service import PDFService
from services.metadata_service import analyze_file as analyze_metadata_file

logger = logging.getLogger(__name__)

ocr_routes = Blueprint("ocr", __name__, url_prefix="/api/ocr")



def is_allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def is_image_file(extension: str) -> bool:
    return extension in {"jpg", "jpeg", "png"}


def is_pdf_file(extension: str) -> bool:
    return extension == "pdf"


def extract_image_metadata(file_path: str, original_filename: str) -> MetadataInfo:
    try:
        from PIL import Image
        import datetime

        file_size = Path(file_path).stat().st_size
        file_size_mb = file_size / (1024 * 1024)

        with Image.open(file_path) as img:
            width, height = img.size
            image_format = img.format or "UNKNOWN"

        return MetadataInfo(
            filename=original_filename,
            file_size_bytes=file_size,
            file_size_mb=round(file_size_mb, 2),
            creation_timestamp=datetime.datetime.now().isoformat(),
            image_width=width,
            image_height=height,
            image_format=image_format,
        )

    except Exception as e:
        logger.error(f"Error extracting image metadata: {str(e)}")
        return MetadataInfo(
            filename=original_filename,
            file_size_bytes=0,
            file_size_mb=0.0,
            creation_timestamp="",
        )


def extract_pdf_metadata(file_path: str, original_filename: str) -> MetadataInfo:
    try:
        import datetime

        file_size = Path(file_path).stat().st_size
        file_size_mb = file_size / (1024 * 1024)

        page_count, _ = PDFService.extract_pdf_metadata(file_path)

        return MetadataInfo(
            filename=original_filename,
            file_size_bytes=file_size,
            file_size_mb=round(file_size_mb, 2),
            creation_timestamp=datetime.datetime.now().isoformat(),
            page_count=page_count,
        )

    except Exception as e:
        logger.error(f"Error extracting PDF metadata: {str(e)}")
        return MetadataInfo(
            filename=original_filename,
            file_size_bytes=0,
            file_size_mb=0.0,
            creation_timestamp="",
        )


def build_api_response(ocr_response):
    response = ocr_response.to_dict()
    raw_text = ocr_response.extracted_text or ""

    response["raw_text"] = raw_text
    response["ocr_confidence"] = (
        round(ocr_response.average_confidence, 2)
        if ocr_response.average_confidence is not None
        else None
    )
    response["extracted_fields"] = ExtractionService.extract_fields(raw_text).model_dump()

    try:
        file_meta = response.get("metadata", {})
        file_path = None
        if file_meta and isinstance(file_meta, dict) and file_meta.get("filename"):
            from config import UPLOADS_DIR
            file_path = str(UPLOADS_DIR / file_meta.get("filename"))

        metadata_analysis = analyze_metadata_file(file_path) if file_path else analyze_metadata_file("")
    except Exception as e:
        logger.error(f"Metadata analysis failed: {e}")
        metadata_analysis = {"metadata": {}, "forensic_flags": [], "metadata_mismatch": False}

    response["metadata_analysis"] = metadata_analysis
    
    _file_path = response.get("metadata", {}).get("filename", "")
    _full_path  = str(UPLOADS_DIR / _file_path) if _file_path else ""
    if _full_path:
        _ela        = run_ela(_full_path)
        _seal_stamp = run_seal_stamp_analysis(_full_path)
        _font       = run_font_analysis(_full_path, ocr_text=response.get("raw_text", ""))
    else:
        _ela = _seal_stamp = _font = None


    response["forensic_signals"] = {
    "ela_score":              _ela.ela_score        if _ela and not _ela.error        else None,
    "ela_detail":             _ela.to_dict()        if _ela and not _ela.error        else None,
    "source_is_pdf":          _ela.source_is_pdf    if _ela and not _ela.error        else False,
    "seal_stamp":             _seal_stamp.to_dict() if _seal_stamp and not _seal_stamp.error else None,
    "seal_found":             _seal_stamp.seal_found       if _seal_stamp else False,
    "stamp_found":            _seal_stamp.stamp_found      if _seal_stamp else False,
    "signature_found":        _seal_stamp.signature_found  if _seal_stamp else False,
    "font_inconsistency":     _font.font_inconsistency     if _font and not _font.error  else False,
    "font_detail":            _font.to_dict()               if _font and not _font.error  else None,
    "metadata_mismatch":      bool(metadata_analysis.get("metadata_mismatch", False)),
    "shadow_artifacts":       False,
}
    try:
       response["risk_report"] = synthesize_risk_report(
           ocr_text=raw_text,
           forensic_signals=response["forensic_signals"],
           extracted_fields=response.get("extracted_fields", {}),
       )
    except Exception as e:
       logger.error(f"Risk report synthesis failed: {e}")
       response["risk_report"] = {
           "risk_level": "UNKNOWN",
           "risk_score": None,
           "summary": "Risk analysis unavailable.",
           "key_findings": [],
           "recommended_action": "Manual review required.",
           "confidence": "LOW",
           "llm_generated": False,
           "error": str(e),
       }

    try:
        import requests as req
        req.post(
            "http://localhost:8000/ingest/ocr-output",
            json=response,
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Failed to forward to ingest API: {e}")

    return response


@ocr_routes.route("", methods=["POST"])
def upload_and_process_ocr():
    start_time = time.time()

    if "file" not in request.files:
        logger.warning("Upload request missing file")
        error = create_error_response(
            error_code="NO_FILE_PROVIDED",
            message="No file provided in request",
            details="Please upload a file with key 'file'",
        )
        return jsonify(error.to_dict()), 400

    file = request.files["file"]

    if file.filename == "":
        logger.warning("Upload request with empty filename")
        error = create_error_response(
            error_code="EMPTY_FILENAME",
            message="Uploaded file has empty name",
        )
        return jsonify(error.to_dict()), 400

    if not is_allowed_file(file.filename):
        logger.warning(f"Unsupported file type: {file.filename}")
        error = create_error_response(
            error_code="INVALID_FILE_TYPE",
            message="File type not supported",
            details=f"Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )
        return jsonify(error.to_dict()), 400

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE_BYTES:
        logger.warning(f"File too large: {file_size} bytes")
        error = create_error_response(
            error_code="FILE_TOO_LARGE",
            message="File exceeds maximum size limit",
            details=f"Max size: {MAX_FILE_SIZE_BYTES / (1024*1024):.0f} MB",
        )
        return jsonify(error.to_dict()), 413

    try:
        UPLOADS_DIR.mkdir(exist_ok=True)
        secure_name = secure_filename(file.filename)
        file_path = UPLOADS_DIR / secure_name

        file.save(str(file_path))
        logger.info(f"File uploaded: {secure_name}")

        extension = get_file_extension(secure_name).lower()

        if is_image_file(extension):
            logger.debug(f"Processing image: {secure_name}")
            response_data = _process_image_file(
                str(file_path),
                secure_name,
                start_time,
            )

        elif is_pdf_file(extension):
            logger.debug(f"Processing PDF: {secure_name}")
            response_data = _process_pdf_file(
                str(file_path),
                secure_name,
                start_time,
            )

        else:
            raise ValueError(f"Unknown file type: {extension}")

        logger.info(f"OCR processing completed for {secure_name}")
        api_response = build_api_response(response_data)
        api_response["doc_type"] = request.form.get("doc_type", "")
        return jsonify(api_response), 200

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        error = create_error_response(
            error_code="PROCESSING_ERROR",
            message="Error processing document",
            details=str(e),
        )
        return jsonify(error.to_dict()), 400

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        error = create_error_response(
            error_code="INTERNAL_ERROR",
            message="Internal server error during processing",
            details=str(e),
        )
        return jsonify(error.to_dict()), 500


def _process_image_file(
    file_path: str,
    filename: str,
    start_time: float,
):
    try:
        text, confidence, ocr_time = OCRService.process_image(file_path)

        if not text.strip():
            logger.warning(f"No text extracted from image: {filename}")

        metadata = extract_image_metadata(file_path, filename)

        processing_time = time.time() - start_time
        response = create_success_response(
            document_type=DocumentType.IMAGE,
            filename=filename,
            metadata=metadata,
            extracted_text=text,
            confidence=confidence,
            processing_time=processing_time,
        )

        if SAVE_OUTPUT_TO_DISK:
            output_name = Path(filename).stem
            OCRService.save_ocr_output(output_name, response.to_dict())

        return response

    except Exception as e:
        logger.error(f"Error processing image file: {str(e)}")
        raise


def _process_pdf_file(
    file_path: str,
    filename: str,
    start_time: float,
):
    try:
        combined_text, page_results, ocr_time = OCRService.process_pdf(file_path)

        if not combined_text.strip():
            logger.warning(f"No text extracted from PDF: {filename}")

        if page_results:
            avg_confidences = [
                p.confidence.average_confidence for p in page_results
            ]
            overall_confidence = sum(avg_confidences) / len(avg_confidences)
            total_words = sum(p.confidence.word_count for p in page_results)
        else:
            overall_confidence = 0.0
            total_words = 0

        from models.response_models import ConfidenceMetrics

        confidence = ConfidenceMetrics(
            average_confidence=overall_confidence,
            word_count=total_words,
        )

        metadata = extract_pdf_metadata(file_path, filename)

        processing_time = time.time() - start_time
        response = create_success_response(
            document_type=DocumentType.PDF,
            filename=filename,
            metadata=metadata,
            extracted_text=combined_text,
            confidence=confidence,
            pages=page_results,
            processing_time=processing_time,
        )

        if SAVE_OUTPUT_TO_DISK:
            output_name = Path(filename).stem
            OCRService.save_ocr_output(output_name, response.to_dict())

        return response

    except Exception as e:
        logger.error(f"Error processing PDF file: {str(e)}")
        raise


@ocr_routes.route("/health", methods=["GET"])
def health_check():
    try:
        tesseract_ok = OCRService.check_tesseract_installation()

        return jsonify(
            {
                "status": "healthy" if tesseract_ok else "degraded",
                "service": "OCR Microservice",
                "tesseract_available": tesseract_ok,
                "version": "1.0.0",
            }
        ), 200

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return (
            jsonify(
                {
                    "status": "unhealthy",
                    "service": "OCR Microservice",
                    "error": str(e),
                }
            ),
            500,
        )
