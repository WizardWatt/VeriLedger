export function updateDashboard(data) {

    // Document Count
    document.getElementById("docCount").textContent = "1";

    // OCR Confidence
    if (data.average_confidence !== undefined) {
        document.getElementById("ocrConfidence").textContent =
            `${Number(data.average_confidence).toFixed(2)}%`;
    }

    // Processing Time
   if (data.processing_time_seconds !== undefined) {
    document.getElementById("processTime").textContent =
        `${Number(data.processing_time_seconds).toFixed(2)} s`;
}

// Risk Level
if (data.risk_report && data.risk_report.risk_level) {

    document.getElementById("riskScore").textContent =
        data.risk_report.risk_level;

} else {

    let confidence = Number(data.average_confidence || 0);
    let risk = "HIGH";

    if (confidence >= 90) {
        risk = "LOW";
    } else if (confidence >= 70) {
        risk = "MEDIUM";
    }

    document.getElementById("riskScore").textContent = risk;
}
}