const historyContainer = document.getElementById("historyContainer");

// ======================================================
// LOAD HISTORY
// ======================================================

function loadHistory() {

    const history =
        JSON.parse(localStorage.getItem("analysisHistory")) || [];

    if (history.length === 0) {

        historyContainer.innerHTML = `

        <div class="text-center py-5">

            <i class="bi bi-clock-history"
               style="font-size:70px;color:#999;"></i>

            <h3 class="mt-3">
                No History Available
            </h3>

            <p class="text-muted">
                Analyze documents to build history.
            </p>

        </div>

        `;

        return;

    }

    let rows = "";

    history.forEach((item, index) => {

        const badgeColor =
            item.riskLevel === "HIGH" ? "danger" :
            item.riskLevel === "MEDIUM" ? "warning" :
            item.riskLevel === "LOW" ? "success" :
            "secondary";

        rows += `

<tr>

<td>${index + 1}</td>

<td>${item.filename}</td>

<td>${item.documentType}</td>

<td>${item.applicant}</td>

<td>${item.pan}</td>

<td>

<span class="badge bg-${badgeColor}">
${item.riskLevel}
</span>

</td>

<td>${item.date}</td>

<td>

<button
class="btn btn-sm btn-primary"
onclick="openReport(${item.id})">

Open

</button>

<button
class="btn btn-sm btn-danger ms-2"
onclick="deleteHistory(${item.id})">

Delete

</button>

</td>

</tr>

`;

    });

    historyContainer.innerHTML = `

<div class="d-flex justify-content-between mb-3">

<h5>

Stored Reports (${history.length})

</h5>

<button
class="btn btn-danger"
onclick="clearHistory()">

<i class="bi bi-trash"></i>

Clear History

</button>

</div>

<div class="table-responsive">

<table class="table table-bordered table-hover align-middle">

<thead class="table-primary">

<tr>

<th>#</th>

<th>File</th>

<th>Type</th>

<th>Applicant</th>

<th>PAN</th>

<th>Risk</th>

<th>Date</th>

<th>Actions</th>

</tr>

</thead>

<tbody>

${rows}

</tbody>

</table>

</div>

`;

}

// ======================================================
// OPEN REPORT
// ======================================================

window.openReport = function (id) {

    const history =
        JSON.parse(localStorage.getItem("analysisHistory")) || [];

    const report =
        history.find(r => r.id === id);

    if (!report) {

        alert("Report not found.");

        return;

    }

    sessionStorage.setItem(
        "analysisResult",
        JSON.stringify(report.fullReport)
    );

    // Open in SAME Electron window
    window.location.href = "report.html";

};

// ======================================================
// DELETE HISTORY
// ======================================================

window.deleteHistory = function (id) {

    let history =
        JSON.parse(localStorage.getItem("analysisHistory")) || [];

    history =
        history.filter(r => r.id !== id);

    localStorage.setItem(
        "analysisHistory",
        JSON.stringify(history)
    );

    loadHistory();

};

// ======================================================
// CLEAR HISTORY
// ======================================================

window.clearHistory = function () {

    if (!confirm("Delete all history?")) return;

    localStorage.removeItem("analysisHistory");

    loadHistory();

};

// ======================================================
// INITIAL LOAD
// ======================================================

loadHistory();