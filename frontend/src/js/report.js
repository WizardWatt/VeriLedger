const data = JSON.parse(sessionStorage.getItem("analysisResult"));
const reportContainer = document.getElementById("reportContainer");

if (!data) {
    reportContainer.innerHTML = `
        <div class="alert alert-danger text-center mt-5" style="max-width:600px;margin:auto;">
            <i class="bi bi-exclamation-triangle-fill" style="font-size:48px;display:block;margin-bottom:15px;"></i>
            <h3>No Report Found</h3>
            <p class="mb-0">Please analyze a document first.</p>
            <button class="btn btn-primary mt-3" onclick="window.location.href='index.html'">
                <i class="bi bi-arrow-left"></i> Go Back
            </button>
        </div>
    `;
} else {
    // =====================================
    // Helper Variables & Data Parsers
    // =====================================
    const risk = data.risk_report || {};
    const forensic = data.forensic_signals || {};
    const metaAnalysis = data.metadata_analysis || {};
    const nestedMetadata = metaAnalysis.metadata || {};
    const elaDetail = forensic.ela_detail || {};
    const copyDetail = forensic.copy_paste_detail || {};
    const sealDetail = forensic.seal_stamp || {};
    
    const filename = data.filename || data.metadata?.filename || "Unknown_File.pdf";
    const rawOCR = data.raw_text || data.extracted_text || "No OCR text available.";
    const generatedTime = new Date().toLocaleString();

    const riskLevel = risk.risk_level || "UNKNOWN";

let riskBadgeClass = "bg-secondary";

switch (riskLevel) {

    case "LOW":
        riskBadgeClass = "bg-success";
        break;

    case "MEDIUM":
        riskBadgeClass = "bg-warning text-dark";
        break;

    case "HIGH":
        riskBadgeClass = "bg-danger";
        break;

}

    // OCR Confidence
    const ocrConfidence = data.average_confidence || data.ocr_confidence || 0;

    // =====================================
    // Key Findings Builder
    // =====================================
    let keyFindingsHTML = "";
    if (risk.key_findings && Array.isArray(risk.key_findings) && risk.key_findings.length > 0) {
        risk.key_findings.forEach(finding => {
            keyFindingsHTML += `
                <li class="list-group-item d-flex align-items-start bg-transparent border-0 ps-0 text-dark py-1">
                    <i class="bi bi-exclamation-triangle-fill text-danger me-2 mt-1"></i>
                    <span>${finding}</span>
                </li>`;
        });
    } else {
        keyFindingsHTML = `<li class="list-group-item text-muted border-0 ps-0">No structural fraud elements flagged.</li>`;
    }

    // =====================================
    // Extracted Information Cards
    // =====================================
    let extractedFieldsHTML = "";
    if (data.extracted_fields) {
        const fields = data.extracted_fields;
        Object.entries(fields).forEach(([key, value]) => {
            if (value !== null && value !== "" && value !== "null" && value !== undefined) {
                const title = key
                    .replace(/_/g, " ")
                    .replace(/\b\w/g, c => c.toUpperCase());
                extractedFieldsHTML += `
                    <div class="field-card">
                        <div class="field-title">${title}</div>
                        <div class="field-value">${value}</div>
                    </div>`;
            }
        });
    }
    if (extractedFieldsHTML === "") {
        extractedFieldsHTML = `<p class="text-muted m-0">No structural fields retrieved.</p>`;
    }

    // =====================================
    // DOM Assembly
    // =====================================
    reportContainer.innerHTML = `
<div class="report-wrapper">

    <!-- ====================================
    1. REPORT HEADER
    ==================================== -->
    <div class="report-header mb-5 border-bottom pb-4 text-start d-flex justify-content-between align-items-end">
        <div>
            <h1 class="mb-1" style="color:#0d4c92; font-weight:700;">VeriLedger Analysis Report</h1>
            <p class="mb-0" style="color:#6c757d; font-size:17px;">Secure Banking Document Verification Platform</p>
        </div>
        <div class="text-end text-muted small">
            <strong>Generated:</strong> ${generatedTime}
        </div>
    </div>

    <!-- ====================================
    2. EXECUTIVE SUMMARY
    ==================================== -->
    <div class="summary-card">
        <h2><i class="bi bi-speedometer2 me-2"></i>Executive Summary</h2>
        <div class="summary-grid">
            <div class="summary-item">
                <span class="label">Risk Level</span>
            <span class="badge ${riskBadgeClass}"
style="padding:10px 24px;font-size:17px;border-radius:25px;">
            </div>
            <div class="summary-item">
                <span class="label">OCR Confidence</span>
                <span>${Number(ocrConfidence).toFixed(2)} %</span>
            </div>
            <div class="summary-item">
                <span class="label">Processing Time</span>
                <span>${Number(data.processing_time_seconds || 0).toFixed(2)} s</span>
            </div>
            <div class="summary-item">
                <span class="label">Word Count</span>
                <span>${data.word_count || "-"}</span>
            </div>
        </div>
    </div>

    <!-- ====================================
    3. DOCUMENT INFORMATION
    ==================================== -->
    <div class="info-card">
        <h2><i class="bi bi-file-earmark-text me-2"></i>Document Information</h2>
        <div class="info-grid">
            <div class="info-item"><span class="label">File Name</span><span>${filename}</span></div>
            <div class="info-item"><span class="label">Document Type</span><span>${data.document_type || "-"}</span></div>
            <div class="info-item"><span class="label">Selected Category</span><span>${data.doc_type || "-"}</span></div>
            <div class="info-item">
    <span class="label">Number of Pages</span>
    <span>${
        data.document_type === "pdf"
            ? (data.metadata?.page_count || "-")
            : "1"
    }</span>
</div>
            <div class="info-item"><span class="label">File Size</span><span>${data.metadata?.file_size_mb || "-"} MB</span></div>
            <div class="info-item"><span class="label">Processing Status</span><span><span class="badge bg-success">${data.status || "success"}</span></span></div>
        </div>
    </div>

<!-- ====================================
4. AI FRAUD ASSESSMENT
==================================== -->

<div class="info-card">

    <h2>
        <i class="bi bi-shield-check me-2"></i>
        AI Fraud Assessment
    </h2>

    <div class="row align-items-center">

        <div class="col-md-3 text-center">

            <div class="small text-muted mb-2">

                Overall Risk

            </div>

            <span class="badge ${riskBadgeClass}"
            style="font-size:18px;padding:12px 28px;border-radius:30px;">

                ${riskLevel}

            </span>

            <div class="mt-3"
            style="font-size:28px;font-weight:700;color:#0d4c92;">

                ${risk.risk_score ?? 0}/100

            </div>

        </div>

        <div class="col-md-9">

            <h5>AI Summary</h5>

            <p>

                ${risk.summary || "No automated summary available."}

            </p>

            <h5 class="mt-4">

                Recommendation

            </h5>

            <p class="fw-semibold">

                ${risk.recommended_action || "-"}

            </p>

        </div>

    </div>

</div>

  
   
    <!-- ====================================
    6. OCR RESULTS
    ==================================== -->
    <div class="info-card">
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h2><i class="bi bi-file-earmark-richtext me-2"></i>OCR Results</h2>
            <span class="badge bg-info text-dark">Confidence: ${Number(ocrConfidence).toFixed(2)}%</span>
        </div>
        <div class="ocr-toolbar">
            <button class="btn btn-outline-primary btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('ocrTextTarget').innerText)">
                <i class="bi bi-clipboard"></i> Copy Plain Text
            </button>
        </div>
        <pre id="ocrTextTarget" class="ocr-box">${rawOCR}</pre>
    </div>

    <!-- ====================================
    7. EXTRACTED INFORMATION
    ==================================== -->
    <div class="info-card">
        <h2><i class="bi bi-card-checklist me-2"></i>Extracted Information</h2>
        <div class="fields-grid">
            ${extractedFieldsHTML}
        </div>
    </div>

    <!-- ====================================
    8. FORENSIC ANALYSIS
    ==================================== -->
    <div class="info-card">
        <h2><i class="bi bi-shield-check me-2"></i>Forensic Analysis</h2>
        <div class="fields-grid">
            
            <!-- Copy Paste Detection -->
            <div class="info-item">
                <span class="label">Copy Paste Detection</span>
                <div class="fw-bold ${forensic.copy_paste_detected ? 'text-danger' : 'text-success'}">${forensic.copy_paste_detected ? '⚠️ Detected' : '✅ Not Detected'}</div>
                <div class="small text-muted mt-1">
                    Score: ${copyDetail.clone_score ?? "N/A"} | 
                    Regions: ${copyDetail.clone_regions?.length || 0}
                </div>
            </div>

            <!-- ELA Analysis -->
            <div class="info-item">
                <span class="label">ELA Analysis</span>
                <div class="fw-bold ${elaDetail.ela_score > 30 ? 'text-danger' : 'text-success'}">Score: ${elaDetail.ela_score ?? "N/A"}</div>
                <div class="small text-muted mt-1">
                    Mean Error: ${elaDetail.mean_pixel_error ?? "N/A"} | 
                    Max Error: ${elaDetail.max_pixel_error ?? "N/A"}
                </div>
            </div>

            <!-- Metadata Analysis -->
            <div class="info-item">
                <span class="label">Metadata Analysis</span>
                <div class="fw-bold ${metaAnalysis.metadata_mismatch ? 'text-danger' : 'text-success'}">${metaAnalysis.metadata_mismatch ? '⚠️ Mismatch Detected' : '✅ Verified'}</div>
                <div class="small text-muted mt-1">Flags: ${metaAnalysis.forensic_flags?.join(', ') || "None"}</div>
            </div>

            <!-- Font Analysis -->
            <div class="info-item">
                <span class="label">Font Analysis</span>
                <div class="fw-bold ${forensic.font_inconsistency ? 'text-danger' : 'text-success'}">${forensic.font_inconsistency ? '⚠️ Inconsistent' : '✅ Consistent'}</div>
                <div class="small text-muted mt-1">
                    Fonts: ${forensic.font_detail?.fonts_found?.join(', ') || "N/A"} | 
                    Score: ${forensic.font_detail?.inconsistency_score ?? "N/A"}
                </div>
            </div>

            <!-- Seal Detection -->
            <div class="info-item">
                <span class="label">Seal Detection</span>
                <div class="fw-bold ${forensic.seal_found ? 'text-success' : 'text-muted'}">${forensic.seal_found ? '✅ Found' : '❌ Not Found'}</div>
                <div class="small text-muted mt-1">
                    Score: ${sealDetail.seal_score ?? "N/A"}% | 
                    Detections: ${sealDetail.detections?.length || 0}
                </div>
            </div>

            
        </div>
    </div>

    <!-- ====================================
    9. METADATA
    ==================================== -->
    <div class="info-card">
        <h2><i class="bi bi-info-circle me-2"></i>Metadata</h2>
        <div class="info-grid">
            <div class="info-item"><span class="label">Created</span><span>${data.metadata?.creation_timestamp || "-"}</span></div>
            <div class="info-item"><span class="label">Modified</span><span>${nestedMetadata.modification_date || "-"}</span></div>
            <div class="info-item"><span class="label">Author</span><span class="text-truncate d-block">${nestedMetadata.author || "-"}</span></div>
            <div class="info-item"><span class="label">Producer</span><span class="text-truncate d-block">${nestedMetadata.producer || "-"}</span></div>
            <div class="info-item"><span class="label">Creator</span><span class="text-truncate d-block">${nestedMetadata.creator || "-"}</span></div>
        </div>
    </div>

    <!-- ====================================
    10. ANALYSIS STATISTICS
    ==================================== -->
    <div class="info-card">
        <h2><i class="bi bi-bar-chart-line me-2"></i>Analysis Statistics</h2>
        <div class="summary-grid" style="grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));">
            <div class="summary-item"><span class="label">Processing Time</span><span>${data.processing_time_seconds || 0}s</span></div>
            <div class="summary-item"><span class="label">OCR Confidence</span><span>${Number(ocrConfidence).toFixed(2)}%</span></div>
            <div class="summary-item"><span class="label">Word Count</span><span>${data.word_count || 0}</span></div>
            <div class="summary-item"><span class="label">Total Pages</span><span>${data.metadata?.page_count || 1}</span></div>
            <div class="summary-item"><span class="label">File Size</span><span>${data.metadata?.file_size_mb || 0} MB</span></div>
        </div>
    </div>

    <!-- ====================================
    11. FOOTER
    ==================================== -->
    <div class="text-center mt-5 mb-4 border-top pt-4 text-muted small">
        <p class="mb-1 fw-bold text-dark">Generated by VeriLedger</p>
        <p class="mb-2 text-uppercase fw-semibold tracking-wider" style="font-size: 11px; letter-spacing: 0.5px;">AI Powered Secure Banking Document Verification</p>
        <div class="d-flex justify-content-center gap-3 mt-1 text-secondary" style="font-size: 11px;">
            <span><strong>Version:</strong> v2.5.0-stable</span>
            <span>•</span>
            <span><strong>System Clock:</strong> ${generatedTime}</span>
        </div>
    </div>

</div>
`;
}