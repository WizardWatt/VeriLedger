import os
from pathlib import Path
from typing import Final

# ============================================================================
# PROJECT ROOT PATHS
# ============================================================================

BASE_DIR: Path = Path(__file__).parent.absolute()
UPLOADS_DIR: Path = BASE_DIR / "uploads"
OUTPUTS_DIR: Path = BASE_DIR / "outputs"
LOGS_DIR: Path = BASE_DIR / "logs"

# Ensure directories exist
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ============================================================================
# FLASK CONFIGURATION
# ============================================================================

FLASK_ENV: str = os.getenv("FLASK_ENV", "development")
DEBUG: bool = FLASK_ENV == "development"
SECRET_KEY: str = os.getenv("SECRET_KEY", "hackathon-ocr-secret-key-2026")
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "5000"))

# ============================================================================
# FILE UPLOAD CONFIGURATION
# ============================================================================

# Allowed file extensions
ALLOWED_EXTENSIONS: Final[set] = {"jpg", "jpeg", "png", "pdf"}

# Maximum file size in MB (100 MB for hackathon)
MAX_FILE_SIZE_MB: int = 100
MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024

# ============================================================================
# OCR CONFIGURATION
# ============================================================================

# Tesseract PSM (Page Segmentation Mode)
# PSM 6: Assume single uniform block of text
OCR_PSM_MODE: str = "6"

# Tesseract confidence threshold (0-100)
# Words below this confidence are flagged
CONFIDENCE_THRESHOLD: int = 50

# Language for OCR (eng = English)
OCR_LANGUAGE: str = "eng"

# ============================================================================
# IMAGE PREPROCESSING CONFIGURATION
# ============================================================================

# Grayscale conversion enabled
ENABLE_GRAYSCALE: bool = True

# Adaptive thresholding block size (must be odd)
THRESHOLDING_BLOCK_SIZE: int = 11

# Adaptive thresholding constant
THRESHOLDING_CONSTANT: int = 2

# Denoising strength (kernel size)
DENOISE_STRENGTH: int = 3

# Image resize factor (1.0 = no resize)
IMAGE_RESIZE_FACTOR: float = 1.5

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOG_FILE: Path = LOGS_DIR / "app.log"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = (
    "%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s"
)

# ============================================================================
# API RESPONSE CONFIGURATION
# ============================================================================

# Include processing metadata in response
INCLUDE_METADATA: bool = True

# Store processed output to disk
SAVE_OUTPUT_TO_DISK: bool = True

# Output format for saved files (json or txt)
OUTPUT_FORMAT: str = "json"

# LLM configuration
LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "mistral")

# ============================================================================
# PDF PROCESSING CONFIGURATION
# ============================================================================

# DPI for PDF to image conversion
PDF_DPI: int = 300

# Maximum pages to process per PDF (safety limit)
MAX_PDF_PAGES: int = 100

# Explicit poppler path (Windows: installed via Chocolatey or standalone)
# Do not rely on PATH detection; use absolute path for reliability
POPPLER_PATH = r"C:\Users\admin\Downloads\Release-26.02.0-0\poppler-26.02.0\Library\bin"

# ============================================================================
# TIMEOUT CONFIGURATION
# ============================================================================

# OCR processing timeout in seconds (30 seconds per page)
OCR_TIMEOUT_SECONDS: int = 30

# PDF conversion timeout in seconds
PDF_CONVERSION_TIMEOUT_SECONDS: int = 120
