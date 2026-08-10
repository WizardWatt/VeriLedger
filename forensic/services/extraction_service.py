import re
from typing import Optional

from models.extracted_models import SharedEntityFields


class ExtractionService:
    @staticmethod
    def _normalize_value(value: Optional[str]) -> Optional[str]:
        if not value:
            return None

        normalized = value.strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.strip(" :\n\t")
        return normalized or None

    @staticmethod
    def _find_pattern(text: str, pattern: str) -> Optional[str]:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            return None
        return ExtractionService._normalize_value(match.group(1))

    @staticmethod
    def extract_fields(raw_text: str) -> SharedEntityFields:
        text = raw_text or ""

        survey_number = ExtractionService._find_pattern(
            text,
            r"survey\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9\-/]+)",
        )
        applicant_id = ExtractionService._find_pattern(
            text,
            r"applicant\s*(?:id|identifier)\s*[:\-]?\s*([A-Z0-9\-/]+)",
        )
        signatory_name = ExtractionService._find_pattern(
            text,
            r"signatory\s*name\s*[:\-]?\s*([A-Za-z .,'&/-]+)",
        )
        registration_office = ExtractionService._find_pattern(
            text,
            r"registration\s*office\s*[:\-]?\s*([A-Za-z0-9 .,'&/-]+)",
        )
        property_address = ExtractionService._find_pattern(
            text,
            r"property\s*address\s*[:\-]?\s*([A-Za-z0-9 .,'#&/-]+)",
        )
        company_name = ExtractionService._find_pattern(
            text,
            r"company\s*name\s*[:\-]?\s*([A-Za-z0-9 .,'&/-]+)",
        )
        pan_number = ExtractionService._find_pattern(
            text,
            r"pan\s*(?:number)?\s*[:\-]?\s*([A-Z]{5}[0-9]{4}[A-Z])",
        )
        if not pan_number:
            pan_number = ExtractionService._find_pattern(
                text,
                r"\b([A-Z]{5}[0-9]{4}[A-Z])\b",
            )

        bank_account_number = ExtractionService._find_pattern(
            text,
            r"(?:bank\s*)?account\s*number\s*[:\-]?\s*([0-9]{6,20})",
        )
        notary_id = ExtractionService._find_pattern(
            text,
            r"notary\s*(?:id|registration)\s*[:\-]?\s*([A-Z0-9\-/]+)",
        )
        advocate_name = ExtractionService._find_pattern(
            text,
            r"advocate\s*name\s*[:\-]?\s*([A-Za-z .,'&/-]+)",
        )

        return SharedEntityFields(
            survey_number=survey_number,
            applicant_id=applicant_id,
            signatory_name=signatory_name,
            registration_office=registration_office,
            property_address=property_address,
            company_name=company_name,
            pan_number=pan_number,
            bank_account_number=bank_account_number,
            notary_id=notary_id,
            advocate_name=advocate_name,
        )
