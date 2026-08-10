import logging
from typing import Optional, Tuple
import cv2
import numpy as np
from PIL import Image

from config import (
    ENABLE_GRAYSCALE,
    THRESHOLDING_BLOCK_SIZE,
    THRESHOLDING_CONSTANT,
    DENOISE_STRENGTH,
    IMAGE_RESIZE_FACTOR,
)

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    @staticmethod
    def to_grayscale(image: np.ndarray) -> np.ndarray:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            logger.debug("Image converted to grayscale")
            return gray
        return image

    @staticmethod
    def apply_adaptive_thresholding(
        image: np.ndarray,
        block_size: int = THRESHOLDING_BLOCK_SIZE,
        constant: int = THRESHOLDING_CONSTANT,
    ) -> np.ndarray:
        if block_size % 2 == 0:
            block_size += 1

        thresh = cv2.adaptiveThreshold(
            image,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block_size,
            constant,
        )
        logger.debug(f"Adaptive thresholding applied (block_size={block_size})")
        return thresh

    @staticmethod
    def denoise(image: np.ndarray, strength: int = DENOISE_STRENGTH) -> np.ndarray:
        strength = max(3, strength)
        if strength % 2 == 0:
            strength += 1

        denoised = cv2.bilateralFilter(image, strength, 75, 75)
        logger.debug(f"Bilateral filtering applied (strength={strength})")
        return denoised

    @staticmethod
    def resize_image(
        image: np.ndarray,
        scale_factor: float = IMAGE_RESIZE_FACTOR,
    ) -> np.ndarray:
        if scale_factor <= 0:
            logger.warning(f"Invalid scale factor {scale_factor}, using 1.0")
            return image

        if scale_factor == 1.0:
            return image

        height, width = image.shape[:2]
        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)

        resized = cv2.resize(
            image,
            (new_width, new_height),
            interpolation=cv2.INTER_CUBIC,
        )
        logger.debug(
            f"Image resized from {width}x{height} to {new_width}x{new_height}"
        )
        return resized

    @staticmethod
    def preprocess_for_ocr(
        image_path: str,
        enable_grayscale: bool = ENABLE_GRAYSCALE,
        enable_thresholding: bool = True,
        enable_denoising: bool = True,
        enable_resizing: bool = True,
    ) -> Tuple[np.ndarray, str]:
        try:
            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Failed to load image from {image_path}")

            original_shape = image.shape
            logger.info(f"Loaded image: {original_shape}")

            if enable_grayscale:
                image = ImagePreprocessor.to_grayscale(image)

            if enable_denoising:
                image = ImagePreprocessor.denoise(image)

            if enable_thresholding:
                image = ImagePreprocessor.apply_adaptive_thresholding(image)

            if enable_resizing:
                image = ImagePreprocessor.resize_image(image)

            pipeline = "grayscale->denoise->threshold->resize"
            logger.info(f"Preprocessing complete. Pipeline: {pipeline}")

            return image, pipeline

        except Exception as e:
            logger.error(f"Error preprocessing image: {str(e)}")
            raise

    @staticmethod
    def pil_to_cv2(pil_image: Image.Image) -> np.ndarray:
        cv2_image = cv2.cvtColor(
            np.array(pil_image.convert("RGB")),
            cv2.COLOR_RGB2BGR,
        )
        return cv2_image

    @staticmethod
    def cv2_to_pil(cv2_image: np.ndarray) -> Image.Image:
        rgb_image = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_image)
        return pil_image
