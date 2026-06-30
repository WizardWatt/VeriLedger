"""
VeriLedger — Canonical Entity Schema
=====================================
THIS IS THE SHARED CONTRACT. Field names here must match exactly across:
  - Person 3's synthetic dataset (CSV / JSON)
  - Person 1's LLM extraction output
  - Graph node/edge keys (graph/forgery_graph.py)
  - Velocity Engine time-series keys (velocity/engine.py)

Never rename a field here without updating all three places.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class DocumentType(str, Enum):
    LAND_RECORD         = "land_record"
    LEGAL_DOCUMENT      = "legal_document"
    FINANCIAL_STATEMENT = "financial_statement"
    # ── New doc types (panel requirement) ────────────────────────────────────
    ITR                 = "itr"             # Income Tax Return / Form 16
    PAYSLIP             = "payslip"         # Salary slip / payslip
    BANK_STATEMENT      = "bank_statement"  # Bank account statement
    GST_RETURN          = "gst_return"      # GST return filing
    # ── Round 2 doc types (panel requirement, batch 2) ───────────────────────
    PROPERTY_TAX_RECEIPT  = "property_tax_receipt"   # Municipal property tax receipt
    NET_WORTH_CERTIFICATE = "net_worth_certificate"  # CA-certified net worth / balance sheet
    APPOINTMENT_LETTER    = "appointment_letter"     # Employer ID / offer / appointment letter
    RENT_LEASE_AGREEMENT  = "rent_lease_agreement"   # Rent / lease agreement (standalone)
    PLAN_APPROVAL_OC      = "plan_approval_oc"       # Building plan approval / occupancy cert
    UDYAM_MSME            = "udyam_msme"             # Udyam / MSME registration certificate
    IDENTITY_DOCUMENT     = "identity_document"      # PAN card / Aadhaar / passport / voter ID


class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


# ── Core Shared Entity Fields ─────────────────────────────────────────────────
# These are the keys that LINK documents together in the Forgery Network Graph.
# Person 3: populate these fields in every synthetic document.
# Person 1: LLM extraction prompt must output exactly these keys.

class SharedEntityFields(BaseModel):
    """Fields that appear across multiple document types and drive graph edges."""
    survey_number:       Optional[str] = Field(None, description="Land parcel identifier (e.g. 'SY-2024-KA-4421')")
    applicant_id:        Optional[str] = Field(None, description="Borrower/applicant unique ID (e.g. 'APPL-9901')")
    signatory_name:      Optional[str] = Field(None, description="Person who signed the document")
    registration_office: Optional[str] = Field(None, description="Sub-registrar / office that registered the document")
    property_address:    Optional[str] = Field(None, description="Full property address string")
    company_name:        Optional[str] = Field(None, description="Firm name (legal docs / financial statements)")
    pan_number:          Optional[str] = Field(None, description="PAN of individual or company (India)")
    bank_account_number: Optional[str] = Field(None, description="Bank account appearing in financial docs")
    notary_id:           Optional[str] = Field(None, description="Notary seal/stamp identifier")
    advocate_name:       Optional[str] = Field(None, description="Advocate name on legal documents")
    # Round 2 linking keys
    ca_membership_number:  Optional[str] = Field(None, description="CA ICAI membership no. — links net worth cert ↔ same CA across applicants")
    municipal_property_id: Optional[str] = Field(None, description="Municipal/ward property ID — links tax receipt ↔ land record")
    plan_approval_number:  Optional[str] = Field(None, description="Approved plan / sanction number — links plan approval ↔ OC")
    udyam_number:           Optional[str] = Field(None, description="Udyam registration number — links MSME cert ↔ GST return via GSTIN")
    aadhaar_number:         Optional[str] = Field(None, description="Aadhaar number (or last 4 digits) — identity anchor across documents")


# ── Document-Type-Specific Fields ─────────────────────────────────────────────

class LandRecordFields(SharedEntityFields):
    doc_type: DocumentType = DocumentType.LAND_RECORD
    document_id:        str   = Field(..., description="Unique document ID (e.g. 'DOC-LR-001')")
    owner_name:         str   = Field(..., description="Registered land owner")
    area_sqft:          Optional[float] = None
    market_value:       Optional[float] = None
    registration_date:  Optional[str]   = None   # ISO date string
    mutation_date:      Optional[str]   = None
    encumbrance_status: Optional[str]   = None   # "clear" | "encumbered"


class LegalDocumentFields(SharedEntityFields):
    doc_type: DocumentType = DocumentType.LEGAL_DOCUMENT
    document_id:          str = Field(...)
    document_subtype:     Optional[str]   = None  # "sale_deed" | "power_of_attorney" | "affidavit" | etc.
    execution_date:       Optional[str]   = None
    party_1_name:         Optional[str]   = None
    party_2_name:         Optional[str]   = None
    stamp_duty_paid:      Optional[float] = None
    consideration_amount: Optional[float] = None


class FinancialStatementFields(SharedEntityFields):
    doc_type: DocumentType = DocumentType.FINANCIAL_STATEMENT
    document_id:       str = Field(...)
    statement_year:    Optional[int]   = None
    annual_income:     Optional[float] = None
    net_worth:         Optional[float] = None
    total_liabilities: Optional[float] = None
    total_assets:      Optional[float] = None
    filing_date:       Optional[str]   = None
    auditor_name:      Optional[str]   = None


# ── NEW: ITR / Form 16 ────────────────────────────────────────────────────────
# Graph links on: pan_number, applicant_id, employer_name (matches payslip),
#                 assessment_year (matches payslip period)
# Velocity tracks: gross_total_income year-over-year for inflation detection
# Fraud signals:
#   - gross_total_income contradicts payslip monthly_gross * 12
#   - tax_paid == 0 with high declared income (fabricated ITR)
#   - same PAN across multiple applicant_ids (identity reuse)

class ITRFields(SharedEntityFields):
    doc_type:           DocumentType  = DocumentType.ITR
    document_id:        str           = Field(...)
    assessment_year:    Optional[str] = Field(None, description="e.g. '2023-24'")
    filing_date:        Optional[str] = None                        # ISO date
    gross_total_income: Optional[float] = None                      # ₹ annual
    taxable_income:     Optional[float] = None
    tax_paid:           Optional[float] = None
    tds_deducted:       Optional[float] = None
    employer_name:      Optional[str]  = Field(None, description="Links to PayslipFields.employer_name")
    form_type:          Optional[str]  = Field(None, description="'ITR-1' | 'ITR-2' | 'Form 16' | etc.")
    acknowledgement_no: Optional[str]  = None                       # ITR-V ack number — unique per filing


# ── NEW: Payslip / Salary Slip ────────────────────────────────────────────────
# Graph links on: pan_number, applicant_id, employer_name (matches ITR),
#                 bank_account_number (matches bank statement credits)
# Velocity tracks: monthly_gross month-over-month for sudden salary jumps
# Fraud signals:
#   - monthly_gross * 12 contradicts ITR gross_total_income
#   - employer_name not found in MCA/GST registry (fabricated employer)
#   - same bank_account_number across different applicant_ids

class PayslipFields(SharedEntityFields):
    doc_type:           DocumentType  = DocumentType.PAYSLIP
    document_id:        str           = Field(...)
    pay_period:         Optional[str] = Field(None, description="e.g. 'March 2024'")
    employer_name:      Optional[str] = Field(None, description="Links to ITRFields.employer_name")
    employee_id:        Optional[str] = None
    monthly_gross:      Optional[float] = None                      # ₹ before deductions
    monthly_net:        Optional[float] = None                      # ₹ take-home
    basic_salary:       Optional[float] = None
    hra:                Optional[float] = None                      # House Rent Allowance
    pf_deducted:        Optional[float] = None                      # Provident Fund
    tds_deducted:       Optional[float] = None                      # Tax Deducted at Source
    # bank_account_number inherited from SharedEntityFields


# ── NEW: Bank Statement ───────────────────────────────────────────────────────
# Graph links on: bank_account_number, pan_number, applicant_id
# Velocity tracks: closing_balance month-over-month, large_credit_count
# Fraud signals:
#   - round-trip: large deposit shortly before loan application date,
#     then large withdrawal after (window-dressing balance)
#   - avg_monthly_credit contradicts payslip monthly_net
#   - multiple applicant_ids sharing same bank_account_number

class BankStatementFields(SharedEntityFields):
    doc_type:             DocumentType  = DocumentType.BANK_STATEMENT
    document_id:          str           = Field(...)
    bank_name:            Optional[str] = None
    ifsc_code:            Optional[str] = None
    statement_from:       Optional[str] = None   # ISO date
    statement_to:         Optional[str] = None   # ISO date
    opening_balance:      Optional[float] = None  # ₹
    closing_balance:      Optional[float] = None  # ₹
    avg_monthly_credit:   Optional[float] = Field(None, description="Average monthly inflow — cross-check vs payslip net")
    avg_monthly_debit:    Optional[float] = None
    large_credit_count:   Optional[int]   = Field(None, description="Credits > ₹1L in statement period — round-trip flag")
    large_debit_count:    Optional[int]   = Field(None, description="Debits > ₹1L in statement period")
    loan_emi_detected:    Optional[bool]  = Field(None, description="True if regular fixed debits suggest undisclosed EMI")
    # bank_account_number inherited from SharedEntityFields


# ── NEW: GST Return ───────────────────────────────────────────────────────────
# Graph links on: gstin, pan_number, company_name, applicant_id
# Velocity tracks: total_turnover quarter-over-quarter
# Fraud signals:
#   - total_turnover contradicts ITR declared business income
#     (GST turnover >> ITR income = tax evasion; GST turnover << ITR = inflated ITR)
#   - tax_liability == 0 with high turnover (fabricated GST)
#   - same GSTIN across different applicant_ids (GSTIN reuse / stolen identity)

class GSTReturnFields(SharedEntityFields):
    doc_type:         DocumentType  = DocumentType.GST_RETURN
    document_id:      str           = Field(...)
    gstin:            Optional[str] = Field(None, description="15-char GST Identification Number — primary graph link key")
    filing_period:    Optional[str] = Field(None, description="e.g. 'Q3 FY2023-24' or 'Oct 2023'")
    return_type:      Optional[str] = Field(None, description="'GSTR-1' | 'GSTR-3B' | 'GSTR-9' | etc.")
    total_turnover:   Optional[float] = Field(None, description="₹ gross turnover declared — cross-check vs ITR")
    taxable_turnover: Optional[float] = None
    tax_liability:    Optional[float] = None                         # ₹ total GST owed
    itc_claimed:      Optional[float] = Field(None, description="Input Tax Credit claimed — large ITC vs low sales = fabrication flag")
    filing_date:      Optional[str]   = None                         # ISO date
    # pan_number + company_name inherited from SharedEntityFields


# ── Round 2 doc types: property tax, net worth, appointment, lease, plan/OC, ──
# ── Udyam/MSME, identity documents ────────────────────────────────────────────
#
# Fraud signals these unlock once linked into the graph + velocity engine:
#   - declared_market_value (tax receipt) vs land_record.market_value mismatch
#   - one CA's ca_membership_number signing net worth certs for many unrelated
#     applicants in a short window (fraud ring)
#   - appointment_letter.employer_name != payslip.employer_name for same applicant
#     (forged appointment letter)
#   - monthly_rent claimed with no matching debit pattern in bank statement
#   - oc_issue_date earlier than plan_approval_date (impossible sequence —
#     backdated document)
#   - udyam declared_annual_turnover vs GST return total_turnover mismatch
#   - aadhaar_number shared across different applicant_ids (identity theft)

class PropertyTaxReceiptFields(SharedEntityFields):
    doc_type:               DocumentType  = DocumentType.PROPERTY_TAX_RECEIPT
    document_id:             str          = Field(...)
    municipality_name:       Optional[str]   = None
    ward_number:             Optional[str]   = None
    assessment_year:         Optional[str]   = Field(None, description="e.g. '2024-25'")
    assessed_value:          Optional[float] = Field(None, description="Municipality's assessed value — cross-check vs land_record.market_value")
    tax_amount_due:          Optional[float] = None
    tax_amount_paid:         Optional[float] = None
    payment_date:            Optional[str]   = None
    receipt_number:          Optional[str]   = None
    property_type:           Optional[str]   = None   # "residential" | "commercial" | "agricultural"
    owner_name:              Optional[str]   = None
    # survey_number + municipal_property_id inherited from SharedEntityFields


class NetWorthCertificateFields(SharedEntityFields):
    doc_type:                DocumentType  = DocumentType.NET_WORTH_CERTIFICATE
    document_id:              str          = Field(...)
    ca_name:                  Optional[str]   = None
    ca_firm_name:             Optional[str]   = None
    certificate_date:         Optional[str]   = None
    as_of_date:               Optional[str]   = Field(None, description="Balance sheet date the figures are as of")
    total_assets:             Optional[float] = None
    total_liabilities:        Optional[float] = None
    net_worth:                Optional[float] = Field(None, description="total_assets - total_liabilities — cross-check vs ITR income")
    annual_income_declared:   Optional[float] = None
    immovable_assets:         Optional[float] = None
    movable_assets:           Optional[float] = None
    purpose:                  Optional[str]   = Field(None, description="e.g. 'home loan' | 'CC limit'")
    # ca_membership_number inherited from SharedEntityFields — primary graph link key


class AppointmentLetterFields(SharedEntityFields):
    doc_type:                DocumentType  = DocumentType.APPOINTMENT_LETTER
    document_id:              str          = Field(...)
    employer_name:            Optional[str]   = Field(None, description="Links to PayslipFields.employer_name and ITRFields.employer_name")
    employee_name:            Optional[str]   = None
    designation:              Optional[str]   = None
    date_of_joining:          Optional[str]   = None
    gross_ctc:                Optional[float] = Field(None, description="Annual cost-to-company — cross-check vs payslip monthly_gross × 12")
    basic_salary:             Optional[float] = None
    letter_date:              Optional[str]   = None
    hr_signatory_name:        Optional[str]   = None
    is_current:               Optional[bool]  = Field(None, description="Whether applicant is still employed here at time of loan")


class RentLeaseAgreementFields(SharedEntityFields):
    doc_type:                DocumentType  = DocumentType.RENT_LEASE_AGREEMENT
    document_id:              str          = Field(...)
    lessor_name:              Optional[str]   = None
    lessee_name:              Optional[str]   = None
    lease_start_date:         Optional[str]   = None
    lease_end_date:           Optional[str]   = None
    lease_term_months:        Optional[int]   = None
    monthly_rent:             Optional[float] = Field(None, description="Claimed monthly rent — cross-check vs bank statement debit pattern")
    security_deposit:         Optional[float] = None
    property_type:            Optional[str]   = None   # "residential" | "commercial"
    notarised:                Optional[bool]  = None
    registered:               Optional[bool]  = Field(None, description="Whether registered at sub-registrar office")
    stamp_duty_paid:          Optional[float] = None
    # pan_number used for lessor's PAN; signatory_name for lessor


class PlanApprovalOCFields(SharedEntityFields):
    doc_type:                DocumentType  = DocumentType.PLAN_APPROVAL_OC
    document_id:              str          = Field(...)
    document_subtype:         Optional[str]   = Field(None, description="'plan_approval' | 'oc' | 'combined'")
    approving_authority:      Optional[str]   = Field(None, description="e.g. 'BBMP' | 'HMDA' | 'PCMC'")
    plan_approval_date:       Optional[str]   = None
    oc_number:                Optional[str]   = None
    oc_issue_date:            Optional[str]   = Field(None, description="Must be AFTER plan_approval_date — earlier date = impossible sequence")
    building_type:            Optional[str]   = None   # "residential" | "commercial" | "mixed"
    total_floors:             Optional[int]   = None
    built_up_area_sqft:       Optional[float] = None
    plot_area_sqft:           Optional[float] = Field(None, description="Should match land_record.area_sqft")
    architect_name:           Optional[str]   = None
    # survey_number + plan_approval_number inherited from SharedEntityFields


class UdyamMSMEFields(SharedEntityFields):
    doc_type:                  DocumentType  = DocumentType.UDYAM_MSME
    document_id:                str          = Field(...)
    enterprise_name:             Optional[str]   = None
    enterprise_type:             Optional[str]   = None   # "proprietorship" | "partnership" | "pvt_ltd"
    enterprise_classification:   Optional[str]   = Field(None, description="'micro' | 'small' | 'medium' — has turnover ceilings")
    nic_code:                    Optional[str]   = None
    registration_date:           Optional[str]   = None
    date_of_commencement:        Optional[str]   = None
    declared_annual_turnover:    Optional[float] = Field(None, description="Cross-check vs GSTReturnFields.total_turnover")
    declared_investment:         Optional[float] = None
    social_category:             Optional[str]   = None
    # gstin + udyam_number inherited — both serve as graph link keys


class IdentityDocumentFields(SharedEntityFields):
    """
    PAN card, Aadhaar card, passport, or voter ID. Metadata only — no photo
    pixels are stored. Photo superimposition detection (CV) is carried via
    forensic.ela_score / forensic.shadow_artifacts on the parent ExtractedDocument.
    """
    doc_type:                  DocumentType  = DocumentType.IDENTITY_DOCUMENT
    document_id:                str          = Field(...)
    id_type:                    Optional[str]   = Field(None, description="'pan' | 'aadhaar' | 'passport' | 'voter_id' | 'dl'")
    id_number:                  Optional[str]   = None   # masked where required
    full_name_on_doc:           Optional[str]   = Field(None, description="Exact name as printed — compare vs signatory_name on other docs")
    date_of_birth:               Optional[str]   = None
    gender:                      Optional[str]   = None
    address_on_document:         Optional[str]   = Field(None, description="Compare vs property_address / rent agreement address")
    issue_date:                  Optional[str]   = None
    expiry_date:                 Optional[str]   = None   # None for PAN/Aadhaar
    issuing_authority:           Optional[str]   = None   # "UIDAI" | "ITD" | "MEA" | "ECI" | "RTO"
    # aadhaar_number inherited from SharedEntityFields — primary graph link key
    # for identity-theft detection (same Aadhaar, different applicant_ids)


# ── Forensic Signals (produced by Person 1's pipeline) ───────────────────────

class ForensicSignals(BaseModel):
    """Tamper signals extracted by OCR + ELA pipeline (Person 1 populates this)."""
    ela_score:           Optional[float] = Field(None, ge=0, le=1, description="Error Level Analysis score; >0.6 is suspicious")
    metadata_mismatch:   bool  = False
    font_inconsistency:  bool  = False
    seal_score:          Optional[float] = Field(None, ge=0, le=1, description="CV seal/stamp confidence; <0.4 is suspicious")
    ocr_confidence:      Optional[float] = Field(None, ge=0, le=1)
    copy_paste_detected: bool  = False
    shadow_artifacts:    bool  = False


# ── Extracted Document (the unified object that flows through the system) ──────

class ExtractedDocument(BaseModel):
    """
    The canonical object produced by Person 1's OCR+LLM pipeline.
    Graph, Velocity Engine, and Report generator all consume this.
    """
    document_id:    str
    doc_type:       DocumentType
    file_path:      Optional[str] = None
    raw_text:       Optional[str] = None

    # Structured fields — exactly one will be populated depending on doc_type
    land_record:    Optional[LandRecordFields]       = None
    legal_doc:      Optional[LegalDocumentFields]    = None
    financial_stmt: Optional[FinancialStatementFields] = None
    itr:            Optional[ITRFields]              = None
    payslip:        Optional[PayslipFields]          = None
    bank_statement: Optional[BankStatementFields]    = None
    gst_return:     Optional[GSTReturnFields]        = None
    # Round 2
    property_tax_receipt:  Optional[PropertyTaxReceiptFields]  = None
    net_worth_certificate: Optional[NetWorthCertificateFields] = None
    appointment_letter:    Optional[AppointmentLetterFields]   = None
    rent_lease_agreement:  Optional[RentLeaseAgreementFields]  = None
    plan_approval_oc:      Optional[PlanApprovalOCFields]      = None
    udyam_msme:            Optional[UdyamMSMEFields]           = None
    identity_document:     Optional[IdentityDocumentFields]    = None

    # Forensic signals from Person 1's pipeline
    forensic:       ForensicSignals = Field(default_factory=ForensicSignals)

    # LLM outputs (Person 1 fills these)
    llm_extracted_fields: Optional[dict] = None   # raw JSON from LLM extraction prompt
    legitimacy_memo:      Optional[str]  = None   # two-sided "for/against" memo from LLM

    # Risk — filled by velocity + graph layers (Person 2)
    velocity_flags: list[str] = Field(default_factory=list)
    graph_flags:    list[str] = Field(default_factory=list)
    risk_level:     RiskLevel = RiskLevel.LOW
    risk_score:     float     = Field(0.0, ge=0, le=1)

    def shared_fields(self) -> SharedEntityFields:
        """Return whichever typed sub-object holds the shared fields."""
        return (
            self.land_record
            or self.legal_doc
            or self.financial_stmt
            or self.itr
            or self.payslip
            or self.bank_statement
            or self.gst_return
            or self.property_tax_receipt
            or self.net_worth_certificate
            or self.appointment_letter
            or self.rent_lease_agreement
            or self.plan_approval_oc
            or self.udyam_msme
            or self.identity_document
            or SharedEntityFields()
        )


# ── Velocity Time-Series Event ────────────────────────────────────────────────

class VelocityEvent(BaseModel):
    """
    A single time-stamped observation for the Behavioral Velocity Engine.
    
    event_type values by doc type:
      ITR          → "income_filing"        value = gross_total_income
      Payslip      → "salary_credit"        value = monthly_gross
      BankStatement→ "closing_balance"      value = closing_balance
                   → "large_credit"         value = credit amount
      GST          → "gst_turnover"         value = total_turnover
      LandRecord   → "property_valuation"   value = market_value
    """
    applicant_id:  str
    event_date:    str    # ISO date
    event_type:    str
    value:         float
    document_id:   Optional[str] = None


# ── Graph Edge (produced by Forgery Network Graph) ────────────────────────────

class GraphEdge(BaseModel):
    source_doc_id:    str
    target_doc_id:    str
    shared_entity:    str    # which field matched (e.g. "survey_number", "gstin")
    shared_value:     str    # the actual value that matched
    suspicion_weight: float  = Field(0.5, ge=0, le=1)


# ── Risk Report Summary (consumed by Person 3's UI) ───────────────────────────

class RiskSummary(BaseModel):
    document_id:    str
    risk_level:     RiskLevel
    risk_score:     float
    velocity_flags: list[str]
    graph_flags:    list[str]
    forensic_flags: list[str]
    top_concern:    Optional[str] = None
