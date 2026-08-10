import logging
from pathlib import Path
from config import LLM_MODEL_NAME
import time

from flask import Flask, jsonify
from flask_cors import CORS

from config import (
    DEBUG,
    HOST,
    PORT,
    SECRET_KEY,
    LOG_FILE,
    LOG_LEVEL,
    LOG_FORMAT,
    POPPLER_PATH,
)
from routes.ocr_routes import ocr_routes
from services.ocr_service import OCRService

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_LEVEL))

    log_file = Path(LOG_FILE)
    log_file.parent.mkdir(exist_ok=True)

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(getattr(logging, LOG_LEVEL))
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, LOG_LEVEL))
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()

def _validate_poppler():
    try:
        from pdf2image.pdf2image import pdfinfo_from_path
        from pathlib import Path
        
        poppler_bin = Path(POPPLER_PATH)
        if poppler_bin.exists():
            logger.info(f"Poppler available at: {POPPLER_PATH}")
            return True
        else:
            logger.warning(f"Poppler path not found: {POPPLER_PATH}")
            return False
    except Exception as e:
        logger.warning(f"Poppler unavailable: {str(e)}")
        return False
    
    
def _warmup_llm():
    import requests as req
    try:
        resp = req.post(
            "http://localhost:11434/api/generate",
            json={"model": LLM_MODEL_NAME, "prompt": "hi", "stream": False,
                  "options": {"num_predict": 1}},
            timeout=180,
        )
        if resp.status_code == 200:
            logger.info(f"LLM warm-up complete — model '{LLM_MODEL_NAME}' loaded")
        else:
            logger.warning(f"LLM warm-up got status {resp.status_code}")
    except Exception as e:
        logger.warning(f"LLM warm-up failed (Ollama may not be running): {e}")


def create_app(config_name: str = "development") -> Flask:
    app = Flask(__name__)

    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["DEBUG"] = DEBUG
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

    CORS(app)

    logger.info("="*80)
    logger.info("Initializing OCR Microservice")
    logger.info("="*80)
    logger.info(f"Environment: {config_name}")
    logger.info(f"Debug Mode: {DEBUG}")
    logger.info(f"Host: {HOST}")
    logger.info(f"Port: {PORT}")

    if OCRService.check_tesseract_installation():
        logger.info("Tesseract OCR is available")
    else:
        logger.warning("Tesseract OCR not found - install before running")

    _validate_poppler()
    _warmup_llm()
    time.sleep(3)

    app.register_blueprint(ocr_routes)

    @app.errorhandler(404)
    def not_found(error):
        logger.warning(f"Resource not found: {error}")
        return (
            jsonify(
                {
                    "status": "failed",
                    "error_code": "NOT_FOUND",
                    "message": "Resource not found",
                }
            ),
            404,
        )

    @app.errorhandler(405)
    def method_not_allowed(error):
        logger.warning(f"Method not allowed: {error}")
        return (
            jsonify(
                {
                    "status": "failed",
                    "error_code": "METHOD_NOT_ALLOWED",
                    "message": "HTTP method not allowed",
                }
            ),
            405,
        )

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "failed",
                    "error_code": "INTERNAL_ERROR",
                    "message": "Internal server error",
                }
            ),
            500,
        )

    @app.route("/")
    def index():
        return jsonify(
            {
                "service": "OCR Microservice",
                "version": "1.0.0",
                "description": "Real-Time Document Integrity & Anomaly Detection Platform",
                "endpoints": {
                    "POST /api/ocr": "Upload document and perform OCR",
                    "GET /api/ocr/health": "Service health check",
                },
                "supported_formats": ["jpg", "jpeg", "png", "pdf"],
            }
        ), 200

    logger.info("Application initialization complete")
    logger.info("="*80)

    return app


if __name__ == "__main__":
    app = create_app("development")
    
    logger.info(f"Starting OCR Microservice on {HOST}:{PORT}")
    logger.info("Press CTRL+C to stop the server")
    
    app.run(host=HOST, port=PORT, debug=DEBUG)
