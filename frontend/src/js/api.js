// =====================================================
// API URLS
// =====================================================

const OCR_API = "http://127.0.0.1:5000";

const GRAPH_API = "http://127.0.0.1:8000";


// =====================================================
// OCR ANALYSIS
// =====================================================

export async function analyzeDocument(file, documentType) {

    const formData = new FormData();

    formData.append("file", file);
    formData.append("doc_type", documentType);

    const response = await fetch(`${OCR_API}/api/ocr`, {

        method: "POST",
        body: formData

    });

    if (!response.ok) {

        throw new Error("OCR Backend Failed");

    }

    const ocrResult = await response.json();

    // Send OCR result to Graph Backend
    await sendToGraphBackend(ocrResult);

    return ocrResult;

}


// =====================================================
// SEND TO PERSON-2 BACKEND
// =====================================================

export async function sendToGraphBackend(ocrResult) {

    try {

        // IMPORTANT
        // Person-2 backend requires doc_type values like:
        // financial_statement
        // legal_document
        // land_record

        let backendDocType = "financial_statement";

        if (ocrResult.doc_type) {

            const type = ocrResult.doc_type.toLowerCase();

            if (type.includes("legal"))
                backendDocType = "legal_document";

            else if (type.includes("land"))
                backendDocType = "land_record";

            else
                backendDocType = "financial_statement";

        }

        const payload = {

            status: ocrResult.status,

            doc_type: backendDocType,

            extracted_fields: ocrResult.extracted_fields || {},

            forensic_signals: {

                ela_score:
                    ocrResult.forensic_signals?.ela_detail?.ela_score || 0,

                metadata_mismatch:
                    ocrResult.forensic_signals?.metadata_mismatch || false,

                font_inconsistency:
                    ocrResult.forensic_signals?.font_inconsistency || false,

                seal_score:
                    ocrResult.forensic_signals?.seal_stamp?.seal_score || 0,

                ocr_confidence:
                    ocrResult.average_confidence || 0,

                copy_paste_detected:
                    ocrResult.forensic_signals?.copy_paste_detected || false,

                shadow_artifacts:
                    ocrResult.forensic_signals?.shadow_artifacts || false

            },

            metadata: {

                filename:
                    ocrResult.metadata?.filename,

                file_size_bytes:
                    ocrResult.metadata?.file_size_bytes,

                creation_timestamp:
                    ocrResult.metadata?.creation_timestamp

            },

            average_confidence:
                ocrResult.average_confidence,

            extracted_text:
                ocrResult.extracted_text,

            processing_time_seconds:
                ocrResult.processing_time_seconds

        };

        const response = await fetch(

            `${GRAPH_API}/ingest/ocr-output`,

            {

                method: "POST",

                headers: {

                    "Content-Type": "application/json"

                },

                body: JSON.stringify(payload)

            }

        );

        if (!response.ok) {

            console.warn("Graph Backend rejected document.");

            return;

        }

        const result = await response.json();

        console.log("Stored in Graph Backend");

        console.log(result);

    }

    catch (err) {

        console.warn("Graph Backend Offline");

        console.warn(err);

    }

}


// =====================================================
// OCR HEALTH
// =====================================================

export async function checkBackendHealth() {

    const response = await fetch(`${OCR_API}/api/ocr/health`);

    return response.ok;

}


/// =====================================================
// GRAPH BACKEND
// =====================================================

export async function getDocuments() {

    const response = await fetch(`${GRAPH_API}/documents`);

    if (!response.ok) {
        throw new Error("Unable to fetch documents.");
    }

    return await response.json();

}


export async function getReport(documentId) {

    const response = await fetch(
        `${GRAPH_API}/report/${documentId}`
    );

    if (!response.ok) {
        throw new Error("Unable to fetch report.");
    }

    return await response.json();

}


export async function getGraph() {

    const response = await fetch(`${GRAPH_API}/graph`);

    return await response.json();

}


export async function getGraphSummary() {

    const response = await fetch(

        `${GRAPH_API}/graph/summary`

    );

    return await response.json();

}


export async function getGraphClusters() {

    const response = await fetch(

        `${GRAPH_API}/graph/clusters`

    );

    return await response.json();

}


export async function getVelocity(applicantId) {

    const response = await fetch(

        `${GRAPH_API}/velocity/${applicantId}`

    );

    return await response.json();

}


export async function checkGraphHealth() {

    const response = await fetch(

        `${GRAPH_API}/health`

    );

    return response.ok;

}