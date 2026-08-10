
import { updateDashboard } from "./dashboard.js";
import { runPipeline, resetPipeline } from "./pipeline.js";
import { analyzeDocument } from "./api.js";

// Clear old report whenever dashboard loads
sessionStorage.removeItem("analysisResult");

let selectedDocument = null;
const viewReportBtn = document.getElementById("viewReportBtn");
viewReportBtn.disabled = true;
const browseBtn = document.getElementById("browseBtn");
const documentInput = document.getElementById("documentInput");
const selectedFile = document.getElementById("selectedFile");
const analyseBtn = document.getElementById("analyseBtn");
viewReportBtn.addEventListener("click", () => {

    const report =
        sessionStorage.getItem("analysisResult");

    if (!report) {

        alert("Please analyze a document first.");

        return;

    }

    window.location.href = "report.html";

});

browseBtn.addEventListener("click", () => {

    documentInput.click();

});

documentInput.addEventListener("change", () => {

    if(documentInput.files.length===0){

        return;

    }

    selectedDocument=documentInput.files[0];

    selectedFile.textContent=selectedDocument.name;

    analyseBtn.disabled=false;

});
analyseBtn.addEventListener("click", async () => {

    if(!selectedDocument){

        alert("Please select a document.");

        return;

    }

    analyseBtn.disabled = true;

    analyseBtn.innerHTML = "Analyzing...";
    resetPipeline();

    runPipeline();

    const formData = new FormData();

    formData.append("file", selectedDocument);

    const category = document.querySelector(".form-select").value;

    formData.append("doc_type", category);

   try {

   const data = await analyzeDocument(
    selectedDocument,
    category
);

console.log(data);

// DEBUG
console.log("Applicant ID:", data.extracted_fields?.applicant_id);
console.log("PAN Number:", data.extracted_fields?.pan_number);
console.log("Extracted Fields:", data.extracted_fields);

updateDashboard(data);
    viewReportBtn.disabled = false;
    sessionStorage.setItem(
        "analysisResult",
        JSON.stringify(data)
    );
    // =============================
// Save Report History
// =============================

let history =
JSON.parse(localStorage.getItem("analysisHistory")) || [];

history.unshift({

    id: Date.now(),

    filename:
        data.filename || selectedDocument.name,

    documentType:
        data.document_type,

    category:
        data.doc_type,

    riskLevel:
        data.risk_report?.risk_level || "UNKNOWN",

    riskScore:
        data.risk_report?.risk_score || 0,

    applicant:
        data.extracted_fields?.applicant_id || "-",

    pan:
        data.extracted_fields?.pan_number || "-",

    company:
        data.extracted_fields?.company_name || "-",

    bank:
        data.extracted_fields?.bank_account_number || "-",

    date:
        new Date().toLocaleString(),

    fullReport: data

});

// keep only latest 50 reports
history = history.slice(0,50);

localStorage.setItem(
    "analysisHistory",
    JSON.stringify(history)
);

   window.location.href = "report.html";

}

    catch(error){

        console.error(error);

        alert("Backend connection failed.");

    }

    finally{

        analyseBtn.disabled = false;

        analyseBtn.innerHTML = '<i class="bi bi-search"></i> Analyze Document';

    }

});