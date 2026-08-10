import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def _parse_pdf_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        s = raw
        if s.startswith("D:"):
            s = s[2:]
        year = int(s[0:4])
        month = int(s[4:6]) if len(s) >= 6 else 1
        day = int(s[6:8]) if len(s) >= 8 else 1
        dt = datetime(year, month, day)
        return dt.date().isoformat()
    except Exception:
        try:
            return datetime.fromisoformat(raw).date().isoformat()
        except Exception:
            return None


def extract_pdf_metadata_detailed(pdf_path: str) -> Dict[str, Optional[str]]:
    from pathlib import Path

    result: Dict[str, Optional[str]] = {
        "author": None,
        "creator": None,
        "producer": None,
        "creation_date": None,
        "modification_date": None,
        "title": None,
        "subject": None,
    }
    

    try:
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf_path))
            info = reader.metadata
        except Exception:
            from PyPDF2 import PdfReader as _PdfReader
            reader = _PdfReader(str(pdf_path))
            info = reader.metadata

        if info is None:
            logger.debug("PDF metadata empty")
            return result

        def _get(key_variants: List[str]) -> Optional[str]:
            for k in key_variants:
                if isinstance(info, dict) and k in info:
                    val = info.get(k)
                    if val:
                        return str(val)
                attr = k.lstrip("/")
                if hasattr(info, attr):
                    val = getattr(info, attr)
                    if val:
                        return str(val)
            return None

        result["author"] = _get(["/Author", "author"])
        result["creator"] = _get(["/Creator", "creator"])
        result["producer"] = _get(["/Producer", "producer"])
        raw_creation = _get(["/CreationDate", "creationDate", "creation_date"])
        raw_mod = _get(["/ModDate", "/ModDate", "modDate", "modification_date"])
        result["creation_date"] = _parse_pdf_date(raw_creation)
        result["modification_date"] = _parse_pdf_date(raw_mod)
        result["title"] = _get(["/Title", "title"])
        result["subject"] = _get(["/Subject", "subject"])

        logger.debug(f"Extracted PDF metadata for {Path(pdf_path).name}: {result}")
        return result

    except Exception as e:
        logger.error(f"Error extracting PDF metadata: {e}", exc_info=True)
        return result


def extract_image_metadata_detailed(image_path: str) -> Dict[str, Optional[Any]]:
    from PIL import Image, ExifTags

    result: Dict[str, Optional[Any]] = {
        "camera_make": None,
        "camera_model": None,
        "software": None,
        "date_taken": None,
        "gps_present": False,
    }

    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if not exif:
                logger.debug("No EXIF metadata found")
                return result

            tag_map = {v: k for k, v in ExifTags.TAGS.items()} if hasattr(ExifTags, "TAGS") else {}

            def _get_tag(name: str) -> Optional[str]:
                tag_id = tag_map.get(name)
                if tag_id and tag_id in exif:
                    return str(exif.get(tag_id))
                return None

            result["camera_make"] = _get_tag("Make")
            result["camera_model"] = _get_tag("Model")
            result["software"] = _get_tag("Software")
            date_val = _get_tag("DateTimeOriginal") or _get_tag("DateTime")
            if date_val:
                try:
                    date_part = date_val.split(" ")[0].replace(":", "-")
                    result["date_taken"] = date_part
                except Exception:
                    result["date_taken"] = date_val

            gps_tag = tag_map.get("GPSInfo")
            if gps_tag and gps_tag in exif and exif.get(gps_tag):
                result["gps_present"] = True

            logger.debug(f"Extracted image metadata for {Path(image_path).name}: {result}")
            return result

    except Exception as e:
        logger.error(f"Error extracting image metadata: {e}", exc_info=True)
        return result


def analyze_metadata(metadata: Dict[str, Optional[Any]], is_scanned_image: bool = False) -> Dict[str, Any]:
    flags: List[str] = []

    if not is_scanned_image:
        if not metadata or all(v in (None, "", False) for v in metadata.values()):
            flags.append("metadata_missing")

    try:
        cd = metadata.get("creation_date")
        md = metadata.get("modification_date")
        if cd and md:
            try:
                cd_dt = datetime.fromisoformat(cd)
                md_dt = datetime.fromisoformat(md)
            except Exception:
                try:
                    cd_dt = datetime.fromisoformat(cd)
                    md_dt = datetime.fromisoformat(md)
                except Exception:
                    cd_dt = None
                    md_dt = None

            if cd_dt and md_dt and md_dt > cd_dt:
                flags.append("document_modified_after_creation")
    except Exception:
        logger.debug("Error comparing creation/modification dates", exc_info=True)

    software_sources = []
    for key in ("software", "creator", "producer", "author", "title"):
        val = metadata.get(key)
        if isinstance(val, str) and val:
            software_sources.append(val.lower())

    editors = ("photoshop", "gimp", "canva", "illustrator")
    for s in software_sources:
        for ed in editors:
            if ed in s:
                flags.append("image_editing_software_detected")
                break
        if "image_editing_software_detected" in flags:
            break

    try:
        creator = (metadata.get("creator") or "")
        producer = (metadata.get("producer") or "")
        if creator and producer:
            ratio = SequenceMatcher(None, creator.lower(), producer.lower()).ratio()
            if ratio < 0.6:
                flags.append("creator_producer_mismatch")
    except Exception:
        logger.debug("Error comparing creator/producer", exc_info=True)

    if metadata.get("gps_present"):
        flags.append("gps_data_present")

    flags = list(dict.fromkeys(flags))

    _mismatch_flags = {
        "document_modified_after_creation",
        "image_editing_software_detected",
        "creator_producer_mismatch",
    }
    metadata_mismatch = any(f in _mismatch_flags for f in flags)

    result = {
        "metadata": metadata,
        "forensic_flags": flags,
        "metadata_mismatch": metadata_mismatch,
    }

    logger.info(f"Metadata analysis result: flags={flags}")
    return result


def analyze_file(path: str) -> Dict[str, Any]:
    p = Path(path)
    suffix = p.suffix.lower()
    is_scanned_image = suffix in {".jpg", ".jpeg", ".png"}
    if suffix == ".pdf":
        meta = extract_pdf_metadata_detailed(path)
    elif is_scanned_image:
        meta = extract_image_metadata_detailed(path)
    else:
        meta = {}

    return analyze_metadata(meta, is_scanned_image=is_scanned_image)
