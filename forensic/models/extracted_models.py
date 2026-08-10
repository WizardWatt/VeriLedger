from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class SharedEntityFields(BaseModel):
    survey_number: Optional[str] = None
    applicant_id: Optional[str] = None
    signatory_name: Optional[str] = None
    registration_office: Optional[str] = None
    property_address: Optional[str] = None
    company_name: Optional[str] = None
    pan_number: Optional[str] = None
    bank_account_number: Optional[str] = None
    notary_id: Optional[str] = None
    advocate_name: Optional[str] = None


class ForensicSignals(BaseModel):
    ela_score: Optional[float] = None
    metadata_mismatch: bool = False
    font_inconsistency: bool = False
    seal_score: Optional[float] = None
    ocr_confidence: Optional[float] = None
    shadow_artifacts: bool = False


class ExtractedDocument(BaseModel):
    status: str = "success"
    ocr_confidence: Optional[float] = None
    raw_text: Optional[str] = None
    extracted_fields: SharedEntityFields = Field(default_factory=SharedEntityFields)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    forensic_signals: ForensicSignals = Field(default_factory=ForensicSignals)
