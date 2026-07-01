import json
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"


def _build_prompt(ocr_text: str, forensic_signals: dict, extracted_fields: dict) -> str:
    flags = []
    ela = forensic_signals.get("ela_score")
    ela_threshold = 40 if forensic_signals.get("source_is_pdf") else 25
    if ela is not None and ela > ela_threshold:
        flags.append(f"ELA (Error Level Analysis) score is {ela:.1f} — values above {ela_threshold} suggest pixel-level tampering")

    if forensic_signals.get("font_inconsistency"):
        detail = forensic_signals.get("font_detail") or {}
        flags.append(f"Font inconsistency detected — multiple font clusters found ({detail.get('font_clusters', 'unknown')} clusters)")

    if forensic_signals.get("metadata_mismatch"):
        flags.append("Metadata mismatch — file creation/modification dates or software signatures are inconsistent")

    if forensic_signals.get("seal_found") is False and forensic_signals.get("stamp_found") is False:
        flags.append("No official seal or stamp detected — expected on this document type")

    if forensic_signals.get("seal_found"):
        flags.append("Official seal found — appears authentic")

    if forensic_signals.get("stamp_found"):
        flags.append("Official stamp found — appears authentic")

    flags_text = "\n".join(f"- {f}" for f in flags) if flags else "- No major forensic anomalies detected"

    fields_summary = []
    for k, v in (extracted_fields or {}).items():
        if v:
            fields_summary.append(f"  {k}: {v}")
    fields_text = "\n".join(fields_summary) if fields_summary else "  (no structured fields extracted)"

    prompt = f"""You are a document forensics expert at a bank. Analyze the following forensic evidence from a scanned document and produce a Risk Intelligence Report.

--- FORENSIC SIGNALS ---
{flags_text}

--- EXTRACTED DOCUMENT FIELDS ---
{fields_text}

--- RAW OCR TEXT (first 800 chars) ---
{ocr_text[:800]}

--- TASK ---
Produce a Risk Intelligence Report in the following JSON format ONLY. Do not write anything outside the JSON.

{{
  "risk_level": "<LOW | MEDIUM | HIGH | CRITICAL>",
  "risk_score": <integer 0-100>,
  "summary": "<2-3 sentence plain-English summary of findings>",
  "key_findings": ["<finding 1>", "<finding 2>", "<finding 3>"],
  "recommended_action": "<one clear action for the bank officer>",
  "confidence": "<LOW | MEDIUM | HIGH>"
}}

Rules:
- risk_score 0-30 = LOW, 31-60 = MEDIUM, 61-85 = HIGH, 86-100 = CRITICAL
- Be concise and factual. Do not hallucinate fields not present in the evidence.
- If no anomalies exist, risk_level should be LOW with score 5-25.
"""
    return prompt


def synthesize_risk_report(
    ocr_text: str,
    forensic_signals: dict,
    extracted_fields: dict,
    model: Optional[str] = None,
) -> dict:
    if model is None:
        try:
            from config import LLM_MODEL_NAME
            model = LLM_MODEL_NAME
        except ImportError:
            model = "llama3"

    prompt = _build_prompt(ocr_text, forensic_signals or {}, extracted_fields or {})

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 200,
        },
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
        resp.raise_for_status()
        raw_output = resp.json().get("response", "")
        logger.info(f"LLM raw output: {raw_output[:200]}")
    except requests.exceptions.ConnectionError:
        logger.error("Ollama not running. Start with: ollama serve")
        return _fallback_report(forensic_signals, error="Ollama not running — start with `ollama serve`")
    except requests.exceptions.Timeout:
        logger.error("Ollama request timed out")
        return _fallback_report(forensic_signals, error="LLM timed out")
    except Exception as e:
        logger.error(f"LLM request failed: {e}")
        return _fallback_report(forensic_signals, error=str(e))

    return _parse_llm_output(raw_output, forensic_signals)


def _parse_llm_output(raw_output: str, forensic_signals: dict) -> dict:
    start = raw_output.find("{")
    end = raw_output.rfind("}") + 1
    if start == -1 or end == 0:
        logger.warning("LLM output contained no JSON block — using fallback")
        return _fallback_report(forensic_signals, error="LLM returned non-JSON output")

    json_str = raw_output[start:end]
    try:
        report = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse LLM JSON: {e}")
        return _fallback_report(forensic_signals, error="LLM JSON parse error")

    valid_levels = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    if report.get("risk_level") not in valid_levels:
        report["risk_level"] = "MEDIUM"

    score = report.get("risk_score")
    if not isinstance(score, (int, float)) or not (0 <= score <= 100):
        report["risk_score"] = 50

    report["risk_score"] = int(report["risk_score"])
    report["llm_generated"] = True
    report["error"] = None
    return report


def _fallback_report(forensic_signals: dict, error: str = "") -> dict:
    score = 0
    findings = []

    ela = forensic_signals.get("ela_score")
    ela_threshold = 40 if forensic_signals.get("source_is_pdf") else 25
    if ela is not None and ela > ela_threshold:
        score += 35
        findings.append(f"ELA score {ela:.1f} indicates possible pixel manipulation")

    if forensic_signals.get("font_inconsistency"):
        score += 25
        findings.append("Font inconsistency detected — possible text substitution")

    if forensic_signals.get("metadata_mismatch"):
        score += 15
        findings.append("File metadata is inconsistent with claimed document history")

    score = min(score, 100)

    if score < 31:
        level = "LOW"
        action = "Proceed with standard verification."
    elif score < 61:
        level = "MEDIUM"
        action = "Flag for manual review before approving."
    elif score < 86:
        level = "HIGH"
        action = "Do not process — escalate to fraud team immediately."
    else:
        level = "CRITICAL"
        action = "Reject document — escalate to legal and fraud teams."

    return {
        "risk_level": level,
        "risk_score": score,
        "summary": f"Rule-based analysis found {len(findings)} forensic anomal{'y' if len(findings)==1 else 'ies'}. "
                   f"Overall risk is assessed as {level}.",
        "key_findings": findings or ["No forensic anomalies detected"],
        "recommended_action": action,
        "confidence": "MEDIUM",
        "llm_generated": False,
        "error": error or None,
    }
