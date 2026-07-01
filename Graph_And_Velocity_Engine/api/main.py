"""
VeriLedger — FastAPI Backend
==============================
All endpoints.  Person 1 will call /ingest/ocr-output from their OCR pipeline.
Person 3's UI will call /report/{document_id} and /graph.

Run: uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations
import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import httpx

from models.entities import (
    ExtractedDocument, VelocityEvent, RiskLevel,
    DocumentType, ForensicSignals,
    LandRecordFields, LegalDocumentFields, FinancialStatementFields,
    ITRFields, PayslipFields, BankStatementFields, GSTReturnFields,
    PropertyTaxReceiptFields, NetWorthCertificateFields, AppointmentLetterFields,
    RentLeaseAgreementFields, PlanApprovalOCFields, UdyamMSMEFields, IdentityDocumentFields,
    SharedEntityFields,
)
from graph.forgery_graph import ForgeryGraph
from velocity.engine import VelocityEngine
from cv.seal_scorer import score_seal_with_breakdown
from db.store import VeriLedgerStore

import io
from PIL import Image
from typing import Any, Optional
from pydantic import BaseModel

app = FastAPI(
    title="VeriLedger API",
    description="Real-time document integrity and anomaly detection for bank underwriting",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Persistence ──────────────────────────────────────────────────────────────
_store = VeriLedgerStore()

# ── In-memory state (now backed by SQLite — restored on startup below) ───────
_graph   = ForgeryGraph()
_engine  = VelocityEngine()
_docs:   dict[str, ExtractedDocument] = {}
_events: list[VelocityEvent] = []


@app.on_event("startup")
async def _restore_state_from_db() -> None:
    """
    Rebuild in-memory state from SQLite on server startup.
    This is what makes the server survive restarts without losing data —
    documents are replayed through the graph so entity-link edges are rebuilt,
    and velocity events are loaded directly since they need no graph wiring.
    """
    global _docs, _events
    _docs = _store.load_all_documents()
    for doc in _docs.values():
        _graph.add_document(doc)
    _events = _store.load_all_velocity_events()
    print(f"[startup] Restored {len(_docs)} documents and {len(_events)} velocity events from {_store.db_path}")


# ══════════════════════════════════════════════════════════════════════════════
# ADAPTER: Person 1 → Person 2 (POST /ingest/ocr-output)
# ══════════════════════════════════════════════════════════════════════════════

class _P1ForensicSignals(BaseModel):
    """Mirrors Person 1's forensic_signals block exactly as they send it."""
    ela_score:           Optional[float] = None
    metadata_mismatch:   bool = False
    font_inconsistency:  bool = False
    seal_score:          Optional[float] = None
    ocr_confidence:      Optional[float] = None
    copy_paste_detected: bool = False
    shadow_artifacts:    bool = False


class _P1Metadata(BaseModel):
    filename:           Optional[str] = None
    file_size_bytes:    Optional[int] = None
    creation_timestamp: Optional[str] = None


class P1OCROutput(BaseModel):
    """
    Full schema of Person 1's OCR pipeline output.
    Person 1 adds ONE field to what they already produce: top-level 'doc_type'.
    Valid values:
      'land_record' | 'legal_document' | 'financial_statement'
      'itr' | 'payslip' | 'bank_statement' | 'gst_return'
      'property_tax_receipt' | 'net_worth_certificate' | 'appointment_letter'
      'rent_lease_agreement' | 'plan_approval_oc' | 'udyam_msme' | 'identity_document'
    """
    status:                    str = "success"
    doc_type:                  str                    # ← Person 1 adds this
    extracted_fields:          dict[str, Any]         # flat dict of all extracted fields
    forensic_signals:          _P1ForensicSignals
    metadata:                  Optional[_P1Metadata] = None
    average_confidence:        Optional[float] = None
    extracted_text:            Optional[str] = None
    processing_time_seconds:   Optional[float] = None


def _map_forensic(p1: _P1ForensicSignals) -> ForensicSignals:
    """
    Person 1 calls it 'forensic_signals', Person 2 calls it 'forensic'.
    Field names inside are identical — direct pass-through.
    """
    return ForensicSignals(
        ela_score=p1.ela_score,
        metadata_mismatch=p1.metadata_mismatch,
        font_inconsistency=p1.font_inconsistency,
        seal_score=p1.seal_score,
        # Person 1 sends ocr_confidence as a percentage (e.g. 76.42).
        # entities.py clamps it to [0, 1] — normalise here.
        ocr_confidence=(p1.ocr_confidence / 100.0) if (p1.ocr_confidence and p1.ocr_confidence > 1.0) else p1.ocr_confidence,
        copy_paste_detected=p1.copy_paste_detected,
        shadow_artifacts=p1.shadow_artifacts,
    )


def _map_submodel(
    doc_type: str,
    fields: dict[str, Any],
    document_id: str,
) -> tuple[
    Optional[LandRecordFields],
    Optional[LegalDocumentFields],
    Optional[FinancialStatementFields],
    Optional[ITRFields],
    Optional[PayslipFields],
    Optional[BankStatementFields],
    Optional[GSTReturnFields],
    Optional[PropertyTaxReceiptFields],
    Optional[NetWorthCertificateFields],
    Optional[AppointmentLetterFields],
    Optional[RentLeaseAgreementFields],
    Optional[PlanApprovalOCFields],
    Optional[UdyamMSMEFields],
    Optional[IdentityDocumentFields],
]:
    """
    Routes Person 1's flat extracted_fields dict into the correct typed sub-model.
    Unknown doc_type → all None (safe: graph falls back to SharedEntityFields).
    """
    land_record = legal_doc = financial_stmt = None
    itr = payslip = bank_statement = gst_return = None
    property_tax_receipt = net_worth_certificate = appointment_letter = None
    rent_lease_agreement = plan_approval_oc = udyam_msme = identity_document = None

    if doc_type == DocumentType.LAND_RECORD.value:
        land_record = LandRecordFields(
            document_id=document_id,
            # SharedEntityFields (graph-linking keys)
            survey_number=fields.get("survey_number"),
            applicant_id=fields.get("applicant_id"),
            signatory_name=fields.get("signatory_name"),
            registration_office=fields.get("registration_office"),
            property_address=fields.get("property_address"),
            pan_number=fields.get("pan_number"),
            advocate_name=fields.get("advocate_name"),
            # LandRecord-specific
            owner_name=fields.get("owner_name") or fields.get("applicant_id") or "UNKNOWN",
            area_sqft=fields.get("area_sqft"),
            market_value=fields.get("market_value"),
            registration_date=fields.get("registration_date"),
            mutation_date=fields.get("mutation_date"),
            encumbrance_status=fields.get("encumbrance_status"),
        )

    elif doc_type == DocumentType.LEGAL_DOCUMENT.value:
        legal_doc = LegalDocumentFields(
            document_id=document_id,
            # SharedEntityFields
            survey_number=fields.get("survey_number"),
            applicant_id=fields.get("applicant_id"),
            signatory_name=fields.get("signatory_name"),
            registration_office=fields.get("registration_office"),
            pan_number=fields.get("pan_number"),
            advocate_name=fields.get("advocate_name"),
            # LegalDoc-specific
            document_subtype=fields.get("document_subtype"),
            execution_date=fields.get("execution_date"),
            party_1_name=fields.get("party_1_name") or fields.get("signatory_name"),
            party_2_name=fields.get("party_2_name"),
            stamp_duty_paid=fields.get("stamp_duty_paid") or fields.get("stamp_duty"),
            consideration_amount=fields.get("consideration_amount"),
        )

    elif doc_type == DocumentType.FINANCIAL_STATEMENT.value:
        financial_stmt = FinancialStatementFields(
            document_id=document_id,
            # SharedEntityFields
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            company_name=fields.get("company_name"),
            bank_account_number=fields.get("bank_account_number") or fields.get("bank_account"),
            # FinancialStmt-specific
            statement_year=fields.get("statement_year") or fields.get("assessment_year"),
            annual_income=fields.get("annual_income"),
            net_worth=fields.get("net_worth"),
            total_liabilities=fields.get("total_liabilities"),
            total_assets=fields.get("total_assets"),
            filing_date=fields.get("filing_date"),
            auditor_name=fields.get("auditor_name"),
        )

    elif doc_type == DocumentType.ITR.value:
        itr = ITRFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            company_name=fields.get("company_name"),
            bank_account_number=fields.get("bank_account_number"),
            assessment_year=fields.get("assessment_year"),
            filing_date=fields.get("filing_date"),
            gross_total_income=fields.get("gross_total_income"),
            taxable_income=fields.get("taxable_income"),
            tax_paid=fields.get("tax_paid"),
            tds_deducted=fields.get("tds_deducted"),
            employer_name=fields.get("employer_name"),
            form_type=fields.get("form_type"),
            acknowledgement_no=fields.get("acknowledgement_no"),
        )

    elif doc_type == DocumentType.PAYSLIP.value:
        payslip = PayslipFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            bank_account_number=fields.get("bank_account_number"),
            pay_period=fields.get("pay_period"),
            employer_name=fields.get("employer_name"),    # graph link → ITR
            employee_id=fields.get("employee_id"),
            monthly_gross=fields.get("monthly_gross"),
            monthly_net=fields.get("monthly_net"),
            basic_salary=fields.get("basic_salary"),
            hra=fields.get("hra"),
            pf_deducted=fields.get("pf_deducted"),
            tds_deducted=fields.get("tds_deducted"),
        )

    elif doc_type == DocumentType.BANK_STATEMENT.value:
        bank_statement = BankStatementFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            bank_account_number=fields.get("bank_account_number"),  # primary graph key
            bank_name=fields.get("bank_name"),
            ifsc_code=fields.get("ifsc_code"),
            statement_from=fields.get("statement_from"),
            statement_to=fields.get("statement_to"),
            opening_balance=fields.get("opening_balance"),
            closing_balance=fields.get("closing_balance"),
            avg_monthly_credit=fields.get("avg_monthly_credit"),
            avg_monthly_debit=fields.get("avg_monthly_debit"),
            large_credit_count=fields.get("large_credit_count"),
            large_debit_count=fields.get("large_debit_count"),
            loan_emi_detected=fields.get("loan_emi_detected"),
        )

    elif doc_type == DocumentType.GST_RETURN.value:
        gst_return = GSTReturnFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),          # graph link → ITR
            company_name=fields.get("company_name"),      # graph link → FinancialStmt
            gstin=fields.get("gstin"),                    # primary graph key
            filing_period=fields.get("filing_period"),
            return_type=fields.get("return_type"),
            total_turnover=fields.get("total_turnover"),
            taxable_turnover=fields.get("taxable_turnover"),
            tax_liability=fields.get("tax_liability"),
            itc_claimed=fields.get("itc_claimed"),
            filing_date=fields.get("filing_date"),
        )

    # ── Round 2: 7 new panel-required doc types ───────────────────────────────

    elif doc_type == DocumentType.PROPERTY_TAX_RECEIPT.value:
        property_tax_receipt = PropertyTaxReceiptFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            survey_number=fields.get("survey_number"),         # graph link → land_record
            property_address=fields.get("property_address"),
            municipal_property_id=fields.get("municipal_property_id") or fields.get("property_id"),
            municipality_name=fields.get("municipality_name") or fields.get("municipality"),
            ward_number=fields.get("ward_number") or fields.get("ward"),
            assessment_year=fields.get("assessment_year"),
            assessed_value=fields.get("assessed_value"),
            tax_amount_due=fields.get("tax_amount_due") or fields.get("tax_due"),
            tax_amount_paid=fields.get("tax_amount_paid") or fields.get("tax_paid"),
            payment_date=fields.get("payment_date"),
            receipt_number=fields.get("receipt_number"),
            property_type=fields.get("property_type"),
            owner_name=fields.get("owner_name") or fields.get("applicant_id"),
        )

    elif doc_type == DocumentType.NET_WORTH_CERTIFICATE.value:
        net_worth_certificate = NetWorthCertificateFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            company_name=fields.get("company_name"),
            bank_account_number=fields.get("bank_account_number"),
            ca_membership_number=fields.get("ca_membership_number") or fields.get("icai_number"),  # primary graph key
            ca_name=fields.get("ca_name"),
            ca_firm_name=fields.get("ca_firm_name") or fields.get("ca_firm"),
            certificate_date=fields.get("certificate_date") or fields.get("cert_date"),
            as_of_date=fields.get("as_of_date") or fields.get("balance_sheet_date"),
            total_assets=fields.get("total_assets"),
            total_liabilities=fields.get("total_liabilities"),
            net_worth=fields.get("net_worth"),
            annual_income_declared=fields.get("annual_income_declared") or fields.get("annual_income"),
            immovable_assets=fields.get("immovable_assets"),
            movable_assets=fields.get("movable_assets"),
            purpose=fields.get("purpose"),
        )

    elif doc_type == DocumentType.APPOINTMENT_LETTER.value:
        appointment_letter = AppointmentLetterFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            signatory_name=fields.get("hr_signatory_name") or fields.get("signatory_name"),
            employer_name=fields.get("employer_name") or fields.get("company_name"),  # graph link → payslip/ITR
            employee_name=fields.get("employee_name") or fields.get("applicant_name"),
            designation=fields.get("designation"),
            date_of_joining=fields.get("date_of_joining") or fields.get("joining_date"),
            gross_ctc=fields.get("gross_ctc") or fields.get("ctc"),
            basic_salary=fields.get("basic_salary"),
            letter_date=fields.get("letter_date") or fields.get("issue_date"),
            hr_signatory_name=fields.get("hr_signatory_name") or fields.get("signatory_name"),
            is_current=fields.get("is_current"),
        )

    elif doc_type == DocumentType.RENT_LEASE_AGREEMENT.value:
        rent_lease_agreement = RentLeaseAgreementFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("lessor_pan") or fields.get("pan_number"),
            survey_number=fields.get("survey_number"),
            property_address=fields.get("property_address"),
            signatory_name=fields.get("lessor_name") or fields.get("signatory_name"),
            notary_id=fields.get("notary_id"),
            advocate_name=fields.get("advocate_name"),
            lessor_name=fields.get("lessor_name"),
            lessee_name=fields.get("lessee_name") or fields.get("applicant_name"),
            lease_start_date=fields.get("lease_start_date") or fields.get("start_date"),
            lease_end_date=fields.get("lease_end_date") or fields.get("end_date"),
            lease_term_months=fields.get("lease_term_months") or fields.get("term_months"),
            monthly_rent=fields.get("monthly_rent") or fields.get("rent"),
            security_deposit=fields.get("security_deposit") or fields.get("deposit"),
            property_type=fields.get("property_type"),
            notarised=fields.get("notarised"),
            registered=fields.get("registered"),
            stamp_duty_paid=fields.get("stamp_duty_paid") or fields.get("stamp_duty"),
        )

    elif doc_type == DocumentType.PLAN_APPROVAL_OC.value:
        plan_approval_oc = PlanApprovalOCFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            survey_number=fields.get("survey_number"),         # graph link → land_record
            property_address=fields.get("property_address"),
            registration_office=fields.get("registration_office") or fields.get("approving_authority"),
            plan_approval_number=fields.get("plan_approval_number") or fields.get("sanction_number"),  # graph key
            document_subtype=fields.get("document_subtype"),
            approving_authority=fields.get("approving_authority") or fields.get("registration_office"),
            plan_approval_date=fields.get("plan_approval_date") or fields.get("approval_date"),
            oc_number=fields.get("oc_number"),
            oc_issue_date=fields.get("oc_issue_date") or fields.get("oc_date"),
            building_type=fields.get("building_type"),
            total_floors=fields.get("total_floors"),
            built_up_area_sqft=fields.get("built_up_area_sqft") or fields.get("built_up_area"),
            plot_area_sqft=fields.get("plot_area_sqft") or fields.get("plot_area"),
            architect_name=fields.get("architect_name"),
        )

    elif doc_type == DocumentType.UDYAM_MSME.value:
        udyam_msme = UdyamMSMEFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            gstin=fields.get("gstin"),                          # graph link → GST return
            company_name=fields.get("company_name") or fields.get("enterprise_name"),
            udyam_number=fields.get("udyam_number") or fields.get("udyam_reg_number"),  # primary graph key
            enterprise_name=fields.get("enterprise_name") or fields.get("company_name"),
            enterprise_type=fields.get("enterprise_type"),
            enterprise_classification=fields.get("enterprise_classification") or fields.get("classification"),
            nic_code=fields.get("nic_code"),
            registration_date=fields.get("registration_date"),
            date_of_commencement=fields.get("date_of_commencement") or fields.get("commencement_date"),
            declared_annual_turnover=fields.get("declared_annual_turnover") or fields.get("annual_turnover") or fields.get("turnover"),
            declared_investment=fields.get("declared_investment") or fields.get("investment"),
            social_category=fields.get("social_category"),
        )

    elif doc_type == DocumentType.IDENTITY_DOCUMENT.value:
        identity_document = IdentityDocumentFields(
            document_id=document_id,
            applicant_id=fields.get("applicant_id"),
            pan_number=fields.get("pan_number"),
            aadhaar_number=fields.get("aadhaar_number"),       # primary graph key
            signatory_name=fields.get("full_name_on_doc") or fields.get("name"),
            id_type=fields.get("id_type") or fields.get("document_type"),
            id_number=fields.get("id_number") or fields.get("pan_number") or fields.get("aadhaar_number"),
            full_name_on_doc=fields.get("full_name_on_doc") or fields.get("name"),
            date_of_birth=fields.get("date_of_birth") or fields.get("dob"),
            gender=fields.get("gender"),
            address_on_document=fields.get("address_on_document") or fields.get("address"),
            issue_date=fields.get("issue_date"),
            expiry_date=fields.get("expiry_date"),
            issuing_authority=fields.get("issuing_authority"),
        )

    return (
        land_record, legal_doc, financial_stmt,
        itr, payslip, bank_statement, gst_return,
        property_tax_receipt, net_worth_certificate, appointment_letter,
        rent_lease_agreement, plan_approval_oc, udyam_msme, identity_document,
    )


def _make_document_id(metadata: Optional[_P1Metadata]) -> str:
    """
    Derive a stable ID from the filename so the same file always gets the
    same document_id across retries. Falls back to random uuid if no filename.
    """
    if metadata and metadata.filename:
        base = metadata.filename.rsplit(".", 1)[0]          # strip extension
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in base)
        return safe[:64]
    return f"DOC-{uuid.uuid4().hex[:8].upper()}"


@app.post("/ingest/ocr-output", tags=["Ingest"])
async def ingest_ocr_output(payload: P1OCROutput):
    """
    **Person 1 integration point.**

    Accepts Person 1's OCR pipeline output and maps it to Person 2's
    ExtractedDocument model, then runs the full fraud detection pipeline.

    Person 1 must add exactly one field to their JSON root:
        `"doc_type": "land_record"`   (or "legal_document" / "financial_statement" / "itr" / "payslip" /
                                        "bank_statement" / "gst_return" / "property_tax_receipt" /
                                        "net_worth_certificate" / "appointment_letter" / "rent_lease_agreement" /
                                        "plan_approval_oc" / "udyam_msme" / "identity_document")

    Everything else (forensic_signals, extracted_fields, extracted_text, metadata)
    is consumed as-is — no other changes needed on Person 1's side.
    """
    # 1. Assign document_id (stable, filename-seeded)
    document_id = _make_document_id(payload.metadata)

    # 2. Validate doc_type is known
    valid_types = {e.value for e in DocumentType}
    if payload.doc_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown doc_type {payload.doc_type!r}. "
                f"Valid values: {sorted(valid_types)}"
            ),
        )

    # 3. Map forensic_signals → forensic (rename only, fields identical)
    forensic = _map_forensic(payload.forensic_signals)

    # 4. Route extracted_fields → typed sub-model
    (
        land_record, legal_doc, financial_stmt,
        itr, payslip, bank_statement, gst_return,
        property_tax_receipt, net_worth_certificate, appointment_letter,
        rent_lease_agreement, plan_approval_oc, udyam_msme, identity_document,
    ) = _map_submodel(payload.doc_type, payload.extracted_fields, document_id)

    # 5. Pull applicant_id for velocity lookup
    applicant_id = (
        payload.extracted_fields.get("applicant_id")
        or payload.extracted_fields.get("pan_number")
        or "UNKNOWN"
    )

    # 6. Assemble ExtractedDocument
    doc = ExtractedDocument(
        document_id=document_id,
        doc_type=DocumentType(payload.doc_type),
        raw_text=payload.extracted_text,           # extracted_text → raw_text
        land_record=land_record,
        legal_doc=legal_doc,
        financial_stmt=financial_stmt,
        itr=itr,
        payslip=payslip,
        bank_statement=bank_statement,
        gst_return=gst_return,
        property_tax_receipt=property_tax_receipt,
        net_worth_certificate=net_worth_certificate,
        appointment_letter=appointment_letter,
        rent_lease_agreement=rent_lease_agreement,
        plan_approval_oc=plan_approval_oc,
        udyam_msme=udyam_msme,
        identity_document=identity_document,
        forensic=forensic,
        llm_extracted_fields=payload.extracted_fields,  # preserve flat dict too
    )

    # 7. Run fraud detection (same pipeline as /analyze/document)
    _graph.add_document(doc)
    doc.graph_flags = _graph.get_flags_for_document(document_id)

    applicant_events = [e for e in _events if e.applicant_id == applicant_id]
    velocity_flags_obj = _engine.analyze(applicant_events)
    doc.velocity_flags = [f.to_string() for f in velocity_flags_obj]
    v_risk_level, v_score = _engine.aggregate_risk(velocity_flags_obj)

    graph_score    = _graph.get_risk_scores().get(document_id, 0.0)
    forensic_score = _forensic_risk(doc.forensic)

    doc.risk_score = min(1.0, max(forensic_score, graph_score, v_score))
    doc.risk_level = _score_to_level(doc.risk_score)

    _docs[document_id] = doc
    _store.save_document(doc)

    return {
        "document_id":    document_id,
        "doc_type":       payload.doc_type,
        "applicant_id":   applicant_id,
        "risk_level":     doc.risk_level.value,
        "risk_score":     round(doc.risk_score, 3),
        "graph_flags":    doc.graph_flags,
        "velocity_flags": doc.velocity_flags,
        "forensic_flags": _forensic_flag_strings(doc.forensic),
        "status":         "ingested",
    }


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL ENDPOINTS (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "documents_loaded": len(_docs)}


@app.get("/health/ollama")
async def health_ollama(host: str = "http://localhost:11434"):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{host}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"status": "ok", "models": models, "host": host}
    except Exception as e:
        return {"status": "unreachable", "error": str(e), "host": host}


# ── Document ingestion (direct — kept for internal/demo use) ──────────────────

@app.post("/analyze/document", response_model=dict)
async def analyze_document(doc: ExtractedDocument):
    """
    Receive a fully-typed ExtractedDocument directly.
    Kept for internal testing and demo dataset injection.
    For Person 1's integration, use POST /ingest/ocr-output instead.
    """
    _graph.add_document(doc)
    graph_flags = _graph.get_flags_for_document(doc.document_id)
    doc.graph_flags = graph_flags

    shared = doc.shared_fields()
    if shared.applicant_id:
        applicant_events = [e for e in _events if e.applicant_id == shared.applicant_id]
        velocity_flags_obj = _engine.analyze(applicant_events)
        doc.velocity_flags = [f.to_string() for f in velocity_flags_obj]
        v_risk_level, v_score = _engine.aggregate_risk(velocity_flags_obj)
    else:
        v_risk_level, v_score = RiskLevel.LOW, 0.0

    graph_scores   = _graph.get_risk_scores()
    graph_score    = graph_scores.get(doc.document_id, 0.0)
    forensic_score = _forensic_risk(doc.forensic)

    doc.risk_score = min(1.0, max(forensic_score, graph_score, v_score))
    doc.risk_level = _score_to_level(doc.risk_score)

    _docs[doc.document_id] = doc
    _store.save_document(doc)

    return {
        "document_id":    doc.document_id,
        "risk_level":     doc.risk_level.value,
        "risk_score":     round(doc.risk_score, 3),
        "graph_flags":    doc.graph_flags,
        "velocity_flags": doc.velocity_flags,
        "graph_summary":  _graph.graph_summary(),
    }


@app.post("/analyze/velocity-events")
async def ingest_velocity_events(events: list[VelocityEvent]):
    _events.extend(events)
    _store.save_velocity_events(events)
    return {"ingested": len(events), "total": len(_events)}


# ── Query endpoints (Person 3's UI) ──────────────────────────────────────────

@app.get("/documents")
async def list_documents():
    return [
        {
            "document_id": doc_id,
            "doc_type":    doc.doc_type.value,
            "risk_level":  doc.risk_level.value,
            "risk_score":  doc.risk_score,
        }
        for doc_id, doc in _docs.items()
    ]


@app.get("/documents/{document_id}")
async def get_document(document_id: str):
    doc = _docs.get(document_id)
    if not doc:
        raise HTTPException(404, f"Document {document_id!r} not found")
    return doc.model_dump()


@app.get("/report/{document_id}")
async def get_risk_report(document_id: str):
    doc = _docs.get(document_id)
    if not doc:
        raise HTTPException(404, f"Document {document_id!r} not found")

    shared = doc.shared_fields()
    applicant_events = (
        [e for e in _events if e.applicant_id == shared.applicant_id]
        if shared.applicant_id else []
    )

    velocity_flags_obj = _engine.analyze(applicant_events)
    forensic_flags = _forensic_flag_strings(doc.forensic)

    return {
        "document_id":    document_id,
        "doc_type":       doc.doc_type.value,
        "risk_level":     doc.risk_level.value,
        "risk_score":     doc.risk_score,
        "forensic_flags":  forensic_flags,
        "velocity_flags":  [f.to_string() for f in velocity_flags_obj],
        "graph_flags":     doc.graph_flags,
        "legitimacy_memo": doc.legitimacy_memo,
        "llm_fields":      doc.llm_extracted_fields,
    }


@app.get("/graph")
async def get_graph():
    return _graph.to_json()


@app.get("/graph/summary")
async def get_graph_summary():
    return _graph.graph_summary()


@app.get("/graph/clusters")
async def get_suspicious_clusters(min_weight: float = 0.6):
    clusters = _graph.get_suspicious_clusters(min_weight=min_weight)
    return {"clusters": clusters, "count": len(clusters)}


@app.get("/velocity/{applicant_id}")
async def get_velocity_analysis(applicant_id: str):
    events = [e for e in _events if e.applicant_id == applicant_id]
    if not events:
        raise HTTPException(404, f"No velocity events for applicant {applicant_id!r}")
    flags = _engine.analyze(events)
    risk_level, score = _engine.aggregate_risk(flags)
    return {
        "applicant_id": applicant_id,
        "event_count":  len(events),
        "flags":        [f.to_string() for f in flags],
        "risk_level":   risk_level.value,
        "risk_score":   round(score, 3),
    }


# ── CV: Seal / Stamp Scoring ──────────────────────────────────────────────────

@app.post("/analyze/seal")
async def analyze_seal(
    file: UploadFile = File(..., description="Cropped stamp/seal image (PNG, JPEG, BMP)"),
    document_id: str | None = None,
):
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"Expected an image file, got content-type {content_type!r}.",
        )

    raw = await file.read()
    if len(raw) > 5_000_000:   # 5 MB guard — seal images should be tiny
        raise HTTPException(
            status_code=400,
            detail=f"Image too large ({len(raw):,} bytes). Please upload a cropped seal/stamp image under 5 MB.",
        )
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not decode image: {exc}")

    breakdown  = score_seal_with_breakdown(image)
    confidence = breakdown.get("final_score", 0.0)

    if document_id and document_id in _docs:
        doc = _docs[document_id]
        if doc.forensic is None:
            doc.forensic = ForensicSignals()
        doc.forensic.seal_score = confidence

    return {
        "document_id": document_id,
        "filename":    file.filename,
        "confidence":  confidence,
        "verdict":     breakdown.get("verdict", "unknown"),
        "breakdown":   {k: v for k, v in breakdown.items() if k not in ("final_score", "verdict")},
        "threshold_guide": {
            "authentic":  ">= 0.60",
            "uncertain":  "0.40 – 0.59",
            "suspicious": "< 0.40",
        },
    }


# ── Reset ─────────────────────────────────────────────────────────────────────

@app.post("/reset")
async def reset(confirm: bool = False):
    """
    Wipe all in-memory state (documents, graph, velocity events).
    Requires ?confirm=true to prevent accidental calls.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm reset. This wipes all in-memory state.",
        )
    global _graph, _docs, _events
    _graph  = ForgeryGraph()
    _docs   = {}
    _events = []
    _store.reset_all()
    return {"status": "reset"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _forensic_risk(f: ForensicSignals) -> float:
    score = 0.0
    if f.ela_score and f.ela_score > 0.6:
        score = max(score, f.ela_score)
    if f.metadata_mismatch:
        score = max(score, 0.65)
    if f.font_inconsistency:
        score = max(score, 0.55)
    if f.copy_paste_detected:
        score = max(score, 0.7)
    if f.seal_score is not None and f.seal_score < 0.4:
        score = max(score, 0.6)
    if f.shadow_artifacts:
        score = max(score, 0.5)
    return score


def _forensic_flag_strings(f: ForensicSignals) -> list[str]:
    flags = []
    if f.ela_score and f.ela_score > 0.6:
        flags.append(f"ELA score {f.ela_score:.2f} — pixel compression anomalies detected")
    if f.metadata_mismatch:
        flags.append("Metadata mismatch — file timestamps inconsistent with document content")
    if f.font_inconsistency:
        flags.append("Font inconsistency — multiple typefaces detected in a single-author document")
    if f.copy_paste_detected:
        flags.append("Copy-paste artifacts detected in document layer")
    if f.seal_score is not None and f.seal_score < 0.4:
        flags.append(f"Seal/stamp confidence {f.seal_score:.2f} — possibly forged or digitally inserted")
    if f.shadow_artifacts:
        flags.append("Shadow/lighting artifacts — image compositing likely")
    return flags


def _score_to_level(score: float) -> RiskLevel:
    if score >= 0.8:  return RiskLevel.CRITICAL
    if score >= 0.6:  return RiskLevel.HIGH
    if score >= 0.35: return RiskLevel.MEDIUM
    return RiskLevel.LOW
