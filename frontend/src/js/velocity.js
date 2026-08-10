const summaryCards = document.getElementById("summaryCards");
const velocityTable = document.getElementById("velocityTable");

// ======================================================
// LOAD VELOCITY DATA
// ======================================================

loadVelocity();

function loadVelocity() {

    const history =
        JSON.parse(localStorage.getItem("analysisHistory")) || [];

    // =====================================
    // NO DATA
    // =====================================

    if (history.length === 0) {

        summaryCards.innerHTML = "";

        velocityTable.innerHTML = `

        <div class="text-center py-5">

            <i class="bi bi-speedometer2"
               style="font-size:70px;color:#999;"></i>

            <h3 class="mt-3">
                No Velocity Data Found
            </h3>

            <p class="text-muted">
                Analyze documents to generate velocity insights.
            </p>

        </div>

        `;

        return;
    }

    // =====================================
    // GROUP BY APPLICANT
    // =====================================

    const applicants = {};

    history.forEach(item => {

        const applicant = item.applicant || "-";

        if (!applicants[applicant]) {

            applicants[applicant] = {

                applicant: applicant,

                pan: item.pan || "-",

                count: 0,

                latest: new Date(item.date),

                latestText: item.date,

                risk: "LOW"

            };

        }

        applicants[applicant].count++;

        const currentDate = new Date(item.date);

        if (currentDate > applicants[applicant].latest) {

            applicants[applicant].latest = currentDate;

            applicants[applicant].latestText = item.date;

        }

    });

    // =====================================
    // CONVERT OBJECT TO ARRAY
    // =====================================

    const data = Object.values(applicants);

    // =====================================
    // CALCULATE VELOCITY
    // =====================================

    let high = 0;
    let medium = 0;
    let low = 0;

    data.forEach(item => {

        if (item.count >= 3) {

            item.risk = "HIGH";
            high++;

        }

        else if (item.count === 2) {

            item.risk = "MEDIUM";
            medium++;

        }

        else {

            item.risk = "LOW";
            low++;

        }

    });

    // =====================================
    // SORT
    // =====================================

    data.sort((a, b) => {

        if (b.count !== a.count) {

            return b.count - a.count;

        }

        return b.latest - a.latest;

    });

    // =====================================
    // SUMMARY CARDS
    // =====================================

    summaryCards.innerHTML = `

<div class="col-lg-3 col-md-6">

<div class="summary-card primary">

<i class="bi bi-people-fill"></i>

<h2>${data.length}</h2>

<p>Total Applicants</p>

</div>

</div>

<div class="col-lg-3 col-md-6">

<div class="summary-card danger">

<i class="bi bi-exclamation-octagon-fill"></i>

<h2>${high}</h2>

<p>High Velocity</p>

</div>

</div>

<div class="col-lg-3 col-md-6">

<div class="summary-card warning">

<i class="bi bi-exclamation-triangle-fill"></i>

<h2>${medium}</h2>

<p>Medium Velocity</p>

</div>

</div>

<div class="col-lg-3 col-md-6">

<div class="summary-card success">

<i class="bi bi-shield-check"></i>

<h2>${low}</h2>

<p>Low Velocity</p>

</div>

</div>

`;

    // =====================================
    // TABLE
    // =====================================

    let rows = "";

    data.forEach((item, index) => {

        let badgeClass = "bg-low";

        if (item.risk === "HIGH")
            badgeClass = "bg-high";

        else if (item.risk === "MEDIUM")
            badgeClass = "bg-medium";

        rows += `

<tr>

<td>${index + 1}</td>

<td>
<strong>${item.applicant}</strong>
</td>

<td>${item.pan}</td>

<td>

<span class="badge bg-primary">

${item.count}

</span>

</td>

<td>${item.latestText}</td>

<td>

<span class="badge ${badgeClass}">

${item.risk}

</span>

</td>

</tr>

`;

    });

    velocityTable.innerHTML = `

<table class="table table-hover align-middle">

<thead>

<tr>

<th>#</th>

<th>Applicant ID</th>

<th>PAN Number</th>

<th>Total Applications</th>

<th>Latest Submission</th>

<th>Velocity Risk</th>

</tr>

</thead>

<tbody>

${rows}

</tbody>

</table>

`;

}