from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional
from enum import Enum
import json


class DocumentType(Enum):
    IMAGE = "image"
    PDF = "pdf"
    UNKNOWN = "unknown"


class ProcessingStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class MetadataInfo:
    filename: str
    file_size_bytes: int
    file_size_mb: float
    creation_timestamp: str
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    image_format: Optional[str] = None
    page_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        return {k: v for k, v in result.items() if v is not None}


@dataclass
class ConfidenceMetrics:
    average_confidence: float
    word_count: int
    high_confidence_words: int = 0
    low_confidence_words: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PageOCRResult:
    page_number: int
    text: str
    confidence: ConfidenceMetrics
    char_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "confidence": self.confidence.to_dict(),
            "char_count": self.char_count,
        }


@dataclass
class StructuredOCROutput:
    raw_text: str
    confidence: ConfidenceMetrics
    metadata: MetadataInfo
    pages: Optional[List[PageOCRResult]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "raw_text": self.raw_text,
            "confidence": self.confidence.to_dict(),
            "metadata": self.metadata.to_dict(),
        }
        if self.pages:
            result["pages"] = [page.to_dict() for page in self.pages]
        return result


@dataclass
class OCRResponse:
    status: ProcessingStatus
    document_type: DocumentType
    filename: str
    message: str = "Processing completed successfully"
    metadata: Optional[MetadataInfo] = None
    average_confidence: Optional[float] = None
    word_count: Optional[int] = None
    extracted_text: Optional[str] = None
    pages: Optional[List[PageOCRResult]] = None
    processing_time_seconds: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "status": self.status.value,
            "document_type": self.document_type.value,
            "filename": self.filename,
            "message": self.message,
        }
        
        if self.metadata:
            result["metadata"] = self.metadata.to_dict()
        if self.average_confidence is not None:
            result["average_confidence"] = round(self.average_confidence, 2)
        if self.word_count is not None:
            result["word_count"] = self.word_count
        if self.extracted_text is not None:
            result["extracted_text"] = self.extracted_text
        if self.pages:
            result["pages"] = [page.to_dict() for page in self.pages]
        if self.processing_time_seconds is not None:
            result["processing_time_seconds"] = round(self.processing_time_seconds, 2)
        if self.error:
            result["error"] = self.error

        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class ErrorResponse:
    status: str = "failed"
    error_code: str = "UNKNOWN_ERROR"
    message: str = "An error occurred"
    details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "status": self.status,
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def create_success_response(
    document_type: DocumentType,
    filename: str,
    metadata: MetadataInfo,
    extracted_text: str,
    confidence: ConfidenceMetrics,
    pages: Optional[List[PageOCRResult]] = None,
    processing_time: Optional[float] = None,
) -> OCRResponse:
    return OCRResponse(
        status=ProcessingStatus.SUCCESS,
        document_type=document_type,
        filename=filename,
        message="OCR processing completed successfully",
        metadata=metadata,
        average_confidence=confidence.average_confidence,
        word_count=confidence.word_count,
        extracted_text=extracted_text,
        pages=pages,
        processing_time_seconds=processing_time,
    )


def create_error_response(
    error_code: str,
    message: str,
    details: Optional[str] = None,
) -> ErrorResponse:
    return ErrorResponse(
        error_code=error_code,
        message=message,
        details=details,
    )
