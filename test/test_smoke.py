"""
VeriLedger — Smoke Test
=========================
Run: python test_smoke.py
Validates entity schema, graph, velocity engine, and API logic — no running server needed.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.entities import (
    ExtractedDocument, LandRecordFields, FinancialStatementFields,
    LegalDocumentFields, ForensicSignals, VelocityEvent,
    DocumentType, RiskLevel
)
from graph.forgery_graph import ForgeryGraph
from velocity.engine import VelocityEngine

PASS = "✅"
FAIL = "❌"

def check(label, condition):
    status = PASS if condition else FAIL
    print(f"  {status} {label}")
    if not condition:
        sys.exit(1)


print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  VeriLedger Smoke Test")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

# ── 1. Entity Schema ──────────────────────────────────────────────────────────
print("1. Entity Schema")

doc_lr = ExtractedDocument(
    document_id="DOC-LR-001",
    doc_type=DocumentType.LAND_RECORD,
    land_record=LandRecordFields(
        document_id="DOC-LR-001",
        owner_name="Ravi Kumar",
        survey_number="SY-2024-KA-4421",
        applicant_id="APPL-9901",
        signatory_name="Meena Reddy",
        registration_office="SR-Office-Whitefield",
        market_value=4_500_000,
        registration_date="2022-03-15",
    ),
    forensic=ForensicSignals(ela_score=0.72, metadata_mismatch=True),
)

doc_legal = ExtractedDocument(
    document_id="DOC-LE-001",
    doc_type=DocumentType.LEGAL_DOCUMENT,
    legal_doc=LegalDocumentFields(
        document_id="DOC-LE-001",
        survey_number="SY-2024-KA-4421",   # ← same survey number — should create a graph edge
        applicant_id="APPL-9902",           # ← different applicant but same land parcel
        signatory_name="Meena Reddy",       # ← same signatory — another edge
        registration_office="SR-Office-Whitefield",
        execution_date="2023-07-01",
        consideration_amount=4_800_000,
    ),
    forensic=ForensicSignals(seal_score=0.31),
)

doc_fin = ExtractedDocument(
    document_id="DOC-FIN-001",
    doc_type=DocumentType.FINANCIAL_STATEMENT,
    financial_stmt=FinancialStatementFields(
        document_id="DOC-FIN-001",
        applicant_id="APPL-9901",           # ← same as doc_lr
        annual_income=1_200_000,
        statement_year=2023,
        net_worth=5_000_000,
    ),
)

check("LandRecord has correct shared fields",
      doc_lr.shared_fields().survey_number == "SY-2024-KA-4421")
check("LegalDoc shares same survey number",
      doc_legal.shared_fields().survey_number == "SY-2024-KA-4421")
check("FinancialStmt shared fields accessible",
      doc_fin.shared_fields().applicant_id == "APPL-9901")

# ── 2. Forgery Network Graph ──────────────────────────────────────────────────
print("\n2. Forgery Network Graph")

graph = ForgeryGraph()
graph.add_documents([doc_lr, doc_legal, doc_fin])

check("Graph has 3 nodes", graph.G.number_of_nodes() == 3)

edges = graph.G.number_of_edges()
check(f"Graph has ≥2 edges ({edges} found)", edges >= 2)

flags_lr = graph.get_flags_for_document("DOC-LR-001")
check("DOC-LR-001 has graph flags", len(flags_lr) > 0)

flags_legal = graph.get_flags_for_document("DOC-LE-001")
check("DOC-LE-001 has graph flags (shared survey + signatory)", len(flags_legal) > 0)

scores = graph.get_risk_scores()
check("Risk scores computed for all nodes", set(scores.keys()) == {"DOC-LR-001", "DOC-LE-001", "DOC-FIN-001"})

clusters = graph.get_suspicious_clusters(min_weight=0.5)
check("Suspicious cluster detected", len(clusters) > 0)

summary = graph.graph_summary()
check("Graph summary has cluster info", summary["suspicious_clusters"] >= 1)

print(f"     Graph: {summary['total_documents']} docs, {summary['total_links']} links, "
      f"{summary['suspicious_clusters']} cluster(s)")
for flag in flags_lr[:2]:
    print(f"     Flag: {flag}")

# ── 3. Velocity Engine ────────────────────────────────────────────────────────
print("\n3. Behavioral Velocity Engine")

velocity_events = [
    VelocityEvent(applicant_id="APPL-9901", event_date="2020-01-01", event_type="income_filing", value=800_000,  document_id="DOC-FIN-001"),
    VelocityEvent(applicant_id="APPL-9901", event_date="2021-01-01", event_type="income_filing", value=850_000,  document_id="DOC-FIN-001"),
    VelocityEvent(applicant_id="APPL-9901", event_date="2022-01-01", event_type="income_filing", value=900_000,  document_id="DOC-FIN-001"),
    VelocityEvent(applicant_id="APPL-9901", event_date="2023-01-01", event_type="income_filing", value=4_500_000, document_id="DOC-FIN-001"),  # spike!
    # Property valuation burst within 30 days
    VelocityEvent(applicant_id="APPL-9901", event_date="2023-03-01", event_type="property_valuation", value=3_000_000),
    VelocityEvent(applicant_id="APPL-9901", event_date="2023-03-10", event_type="property_valuation", value=4_200_000),
    VelocityEvent(applicant_id="APPL-9901", event_date="2023-03-20", event_type="property_valuation", value=4_800_000),
    VelocityEvent(applicant_id="APPL-9901", event_date="2023-03-28", event_type="property_valuation", value=4_700_000),
]

engine = VelocityEngine()
flags = engine.analyze(velocity_events)
risk_level, score = engine.aggregate_risk(flags)

check("Velocity flags detected", len(flags) > 0)
check("Velocity spike detected (income jumped 400% in one year)",
      any(f.rule == "VELOCITY_SPIKE" for f in flags))
check("Compression burst detected (4 valuations in 28 days)",
      any(f.rule == "COMPRESSION_BURST" for f in flags))
check("Risk level is HIGH or CRITICAL",
      risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL))

print(f"     {len(flags)} flag(s), risk={risk_level.value}, score={score:.2f}")
for f in flags:
    print(f"     [{f.rule}] {f.detail[:80]}…")

# ── 4. Serialization ──────────────────────────────────────────────────────────
print("\n4. Serialization / API-readiness")

graph_json = graph.to_json()
check("Graph serializes to JSON", "nodes" in graph_json and "links" in graph_json)
check("Graph JSON has correct node count", len(graph_json["nodes"]) == 3)

doc_dict = doc_lr.model_dump()
check("ExtractedDocument serializes to dict", isinstance(doc_dict, dict))
check("document_id preserved", doc_dict["document_id"] == "DOC-LR-001")

# ── 5. CV Seal Scorer ─────────────────────────────────────────────────────────
print("\n5. CV Seal Scorer")

from PIL import Image as PILImage
import numpy as np
from cv.seal_scorer import score_seal, score_seal_with_breakdown

def _make_synthetic_seal(size=120, kind="circle"):
    """
    Create a synthetic PIL image that mimics a stamp.
      kind='circle'  → dark circle on white  (should score reasonably high)
      kind='blank'   → solid white            (should score low)
      kind='noise'   → random noise           (should score low)
    """
    img = PILImage.new("RGB", (size, size), color=(255, 255, 255))
    arr = np.array(img)
    cx, cy, r = size // 2, size // 2, size // 2 - 8
    if kind == "circle":
        ys, xs = np.ogrid[:size, :size]
        dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        # Filled ring: outer edge dark, inner white (mimics a real stamp)
        ring_mask = (dist >= r - 6) & (dist <= r)
        arr[ring_mask] = [30, 30, 30]
        # Add cross-hair lines inside like a typical official seal
        arr[cy - 2 : cy + 2, cx - r + 8 : cx + r - 8] = [50, 50, 50]
        arr[cy - r + 8 : cy + r - 8, cx - 2 : cx + 2] = [50, 50, 50]
    elif kind == "noise":
        arr = np.random.randint(0, 255, (size, size, 3), dtype=np.uint8)
    # blank: leave all white
    return PILImage.fromarray(arr)

seal_img   = _make_synthetic_seal(kind="circle")
blank_img  = _make_synthetic_seal(kind="blank")
noise_img  = _make_synthetic_seal(kind="noise")
tiny_img   = PILImage.new("RGB", (10, 10), color=(0, 0, 0))

# Basic type and range checks
score_circle = score_seal(seal_img)
check("score_seal returns a float",          isinstance(score_circle, float))
check("score in [0, 1]",                     0.0 <= score_circle <= 1.0)
check("circle seal scores above blank",      score_circle > score_seal(blank_img))

# Breakdown dict checks
bd = score_seal_with_breakdown(seal_img)
check("breakdown is a dict",                 isinstance(bd, dict))
check("breakdown has final_score key",       "final_score" in bd)
check("breakdown has verdict key",           "verdict" in bd)
check("breakdown final_score matches score_seal",
      abs(bd["final_score"] - score_circle) < 1e-6)
check("verdict is a known string",
      bd["verdict"] in ("authentic", "uncertain — manual review recommended",
                        "suspicious — possible forgery"))

# Edge-case: tiny image returns 0.5 fallback
score_tiny = score_seal(tiny_img)
check("tiny image returns 0.5 fallback",     score_tiny == 0.5)

print(f"     circle={score_circle:.4f}  blank={score_seal(blank_img):.4f}  "
      f"noise={score_seal(noise_img):.4f}  tiny={score_tiny}")
print(f"     verdict: {bd['verdict']}")

# ── 6. Duplicate field bug regression ────────────────────────────────────────
print("\n6. Graph — duplicate shared_fields regression")

g2 = ForgeryGraph()
# Add the same two documents twice — should not double-count fields
g2.add_document(doc_lr)
g2.add_document(doc_legal)
g2.add_document(doc_lr)     # duplicate add — must be idempotent on shared_fields
g2.add_document(doc_legal)

for u, v, data in g2.G.edges(data=True):
    fields = data.get("shared_fields", [])
    check(
        f"No duplicate field names in edge {u}↔{v} (got {fields})",
        len(fields) == len(set(fields)),
    )

flags_dedup = g2.get_flags_for_document("DOC-LR-001")
# Verify flag strings don't repeat the same field name within a single flag
for flag in flags_dedup:
    if "Shares [" in flag:
        inside = flag.split("[")[1].split("]")[0]
        parts = [p.strip() for p in inside.split(",")]
        check(
            f"Flag string has no duplicate field tokens ({inside!r})",
            len(parts) == len(set(parts)),
        )

print(f"     {len(flags_dedup)} flag(s), no duplicates")

# ── 7. API endpoint smoke (TestClient — no live server needed) ────────────────
print("\n7. API — /analyze/seal endpoint (TestClient)")

try:
    from fastapi.testclient import TestClient
    import io as _io

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from api.main import app

    client = TestClient(app)

    # Save synthetic seal to bytes
    buf = _io.BytesIO()
    seal_img.save(buf, format="PNG")
    buf.seek(0)

    resp = client.post(
        "/analyze/seal",
        files={"file": ("test_seal.png", buf, "image/png")},
        params={"document_id": "DOC-LR-001"},
    )
    check("POST /analyze/seal returns 200",         resp.status_code == 200)
    body = resp.json()
    check("Response has confidence key",            "confidence" in body)
    check("Response confidence in [0,1]",           0.0 <= body["confidence"] <= 1.0)
    check("Response has verdict key",               "verdict" in body)
    check("Response has breakdown key",             "breakdown" in body)
    check("Response has threshold_guide key",       "threshold_guide" in body)
    print(f"     confidence={body['confidence']}  verdict={body['verdict']!r}")

    # Bad content-type should 400
    buf2 = _io.BytesIO(b"not an image")
    resp_bad = client.post(
        "/analyze/seal",
        files={"file": ("doc.pdf", buf2, "application/pdf")},
    )
    check("Non-image upload returns 400",           resp_bad.status_code == 400)

    # Health check still works
    resp_health = client.get("/health/ollama")
    check("/health/ollama returns 200 or 503",      resp_health.status_code in (200, 503))

except ImportError:
    print("     [SKIP] fastapi.testclient not available — install httpx to enable")

print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  All checks passed — system is wired correctly.")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")