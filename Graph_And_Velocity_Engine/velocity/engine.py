"""
VeriLedger — Behavioral Velocity Engine
============================================
Detects statistically implausible timelines in per-applicant time-series data.

Rules applied:
  WITHIN a single event_type series (existing):
    1. Z_SCORE_SPIKE      — single value > N std-devs above applicant's own baseline
    2. VELOCITY_SPIKE     — % change between consecutive events exceeds threshold
    3. COMPRESSION_BURST  — multiple events in suspiciously short time window
    4. REVERSAL_ANOMALY   — value drops sharply after a suspicious peak (cook-the-books)

  CROSS event_type (new — task 3):
    5. PAYSLIP_ITR_CONTRADICTION  — payslip-implied annual income contradicts ITR declared income
    6. BANK_ROUND_TRIP            — large deposit appears shortly before loan application,
                                    then disappears (balance window-dressing)
"""

from __future__ import annotations
import logging
import statistics
from datetime import date, datetime, timedelta
from typing import Optional
from models.entities import VelocityEvent, RiskLevel

logger = logging.getLogger(__name__)


def _safe_date(event_date: str, fallback: "date | None" = None) -> date:
    """
    Parse an ISO date string safely.
    Returns fallback (default: today) instead of crashing on bad input.
    Logs a warning so malformed dates are visible during debugging.
    """
    try:
        return datetime.fromisoformat(str(event_date)).date()
    except (ValueError, TypeError, AttributeError):
        result = fallback or date.today()
        logger.warning("VelocityEngine: malformed event_date %r — using %s", event_date, result)
        return result

# ── Tunable thresholds ────────────────────────────────────────────────────────
Z_SCORE_THRESHOLD      = 2.5   # flag if a single value is >2.5 std-devs above baseline
VELOCITY_PCT_THRESHOLD = 0.5   # flag if YoY / sequential change exceeds 50%
BURST_WINDOW_DAYS      = 30    # flag if >N events of same type within this window
BURST_COUNT_THRESHOLD  = 3
REVERSAL_DROP_PCT      = 0.3   # flag if value drops >30% after a peak
MIN_EVENTS_FOR_STATS   = 3     # need at least this many events to compute z-scores

# ── Task 3 thresholds ─────────────────────────────────────────────────────────
# PAYSLIP_ITR_CONTRADICTION
PAYSLIP_ITR_TOLERANCE  = 0.25  # allow 25% gap (bonuses, arrears, part-year employment)
                                # flag if |implied_annual - itr_income| / itr_income > 0.25

# BANK_ROUND_TRIP
ROUND_TRIP_WINDOW_DAYS  = 90   # look for large deposit within 90 days before loan application
ROUND_TRIP_DROP_WINDOW  = 60   # then look for matching large withdrawal within 60 days after
ROUND_TRIP_MIN_AMOUNT   = 100_000   # only flag credits >= ₹1L (noise filter)
ROUND_TRIP_DROP_PCT     = 0.6  # balance must drop ≥60% of the peak credit to qualify

# ── Round 2 thresholds ────────────────────────────────────────────────────────
# NET_WORTH_INFLATION
NET_WORTH_INCOME_RATIO_MAX = 15.0  # net worth > 15x annual ITR income is implausible
NET_WORTH_SPIKE_PCT        = 0.40  # net worth jumped >40% between consecutive certs

# PROPERTY_TAX_VALUE_CONTRADICTION
PROPERTY_TAX_VALUE_DIVERGENCE_PCT = 0.30  # assessed vs declared market value differ by >30%

# OC_BEFORE_APPROVAL
OC_BEFORE_APPROVAL_SEVERITY = 0.95  # near-certain forgery signal — impossible date sequence


class VelocityFlag:
    def __init__(self, rule: str, event: VelocityEvent, detail: str, severity: float):
        self.rule     = rule
        self.event    = event
        self.detail   = detail
        self.severity = severity   # 0–1

    def to_string(self) -> str:
        return f"[{self.rule}] {self.detail} (event: {self.event.event_date}, severity: {self.severity:.2f})"


class VelocityEngine:

    def analyze(self, events: list[VelocityEvent]) -> list[VelocityFlag]:
        """
        Analyze a list of events (all for one applicant, or mixed).
        Returns a flat list of VelocityFlags.

        Two passes:
          Pass 1 — per (applicant_id, event_type) group: z-score, velocity, burst, reversal
          Pass 2 — per applicant_id across types: payslip/ITR contradiction, bank round-trip
        """
        flags: list[VelocityFlag] = []

        # ── Pass 1: within-type rules ─────────────────────────────────────────
        groups: dict[tuple[str, str], list[VelocityEvent]] = {}
        for ev in events:
            key = (ev.applicant_id, ev.event_type)
            groups.setdefault(key, []).append(ev)

        for (applicant_id, event_type), group in groups.items():
            sorted_events = sorted(group, key=lambda e: e.event_date)
            values = [e.value for e in sorted_events]

            flags += self._check_zscore_spike(sorted_events, values)
            flags += self._check_velocity_spike(sorted_events, values)
            flags += self._check_compression_burst(sorted_events)
            flags += self._check_reversal(sorted_events, values)

        # ── Pass 2: cross-type rules (Task 3) ────────────────────────────────
        # Group all events by applicant
        by_applicant: dict[str, list[VelocityEvent]] = {}
        for ev in events:
            by_applicant.setdefault(ev.applicant_id, []).append(ev)

        for applicant_id, appl_events in by_applicant.items():
            flags += self._check_payslip_itr_contradiction(appl_events)
            flags += self._check_bank_round_trip(appl_events)
            flags += self._check_net_worth_inflation(appl_events)
            flags += self._check_property_tax_value_contradiction(appl_events)
            flags += self._check_oc_before_approval(appl_events)

        return flags

    # ── Pass 1 rules (unchanged) ──────────────────────────────────────────────

    def _check_zscore_spike(self, events: list[VelocityEvent], values: list[float]) -> list[VelocityFlag]:
        flags = []
        if len(values) < MIN_EVENTS_FOR_STATS:
            return flags

        mean  = statistics.mean(values)
        stdev = statistics.stdev(values)
        if stdev == 0:
            return flags

        for ev, val in zip(events, values):
            z = (val - mean) / stdev
            if z > Z_SCORE_THRESHOLD:
                severity = min(1.0, (z - Z_SCORE_THRESHOLD) / Z_SCORE_THRESHOLD + 0.5)
                flags.append(VelocityFlag(
                    rule="Z_SCORE_SPIKE",
                    event=ev,
                    detail=(
                        f"{ev.event_type} value {val:,.0f} is {z:.1f}σ above applicant baseline "
                        f"(mean={mean:,.0f}, stdev={stdev:,.0f})"
                    ),
                    severity=severity,
                ))
        return flags

    def _check_velocity_spike(self, events: list[VelocityEvent], values: list[float]) -> list[VelocityFlag]:
        flags = []
        for i in range(1, len(events)):
            prev_val = values[i - 1]
            curr_val = values[i]
            if prev_val == 0:
                continue
            pct_change = (curr_val - prev_val) / abs(prev_val)
            if pct_change > VELOCITY_PCT_THRESHOLD:
                severity = min(1.0, pct_change / (VELOCITY_PCT_THRESHOLD * 3))
                flags.append(VelocityFlag(
                    rule="VELOCITY_SPIKE",
                    event=events[i],
                    detail=(
                        f"{events[i].event_type} jumped {pct_change*100:.0f}% between "
                        f"{events[i-1].event_date} ({prev_val:,.0f}) → "
                        f"{events[i].event_date} ({curr_val:,.0f})"
                    ),
                    severity=severity,
                ))
        return flags

    def _check_compression_burst(self, events: list[VelocityEvent]) -> list[VelocityFlag]:
        """Flag if too many events of the same type cluster in a short window."""
        flags = []
        if len(events) < BURST_COUNT_THRESHOLD:
            return flags

        dates = [_safe_date(e.event_date) for e in events]

        for i in range(len(events)):
            burst = [
                j for j in range(len(events))
                if 0 <= (dates[j] - dates[i]).days <= BURST_WINDOW_DAYS
            ]
            if len(burst) >= BURST_COUNT_THRESHOLD:
                flags.append(VelocityFlag(
                    rule="COMPRESSION_BURST",
                    event=events[i],
                    detail=(
                        f"{len(burst)} '{events[i].event_type}' events within "
                        f"{BURST_WINDOW_DAYS} days of {events[i].event_date} — "
                        f"statistically implausible activity burst"
                    ),
                    severity=0.75,
                ))
                break   # one flag per group is enough
        return flags

    def _check_reversal(self, events: list[VelocityEvent], values: list[float]) -> list[VelocityFlag]:
        """Flag sharp drop after a peak — classic 'inflate then correct' pattern."""
        flags = []
        if len(values) < 3:
            return flags

        peak_idx = values.index(max(values))
        if peak_idx == 0 or peak_idx == len(values) - 1:
            return flags   # peak must be internal

        peak_val = values[peak_idx]
        next_val = values[peak_idx + 1]
        drop_pct = (peak_val - next_val) / peak_val if peak_val > 0 else 0

        if drop_pct > REVERSAL_DROP_PCT:
            severity = min(1.0, drop_pct / (REVERSAL_DROP_PCT * 2) + 0.3)
            flags.append(VelocityFlag(
                rule="REVERSAL_ANOMALY",
                event=events[peak_idx + 1],
                detail=(
                    f"{events[peak_idx].event_type} peaked at {peak_val:,.0f} on "
                    f"{events[peak_idx].event_date} then dropped {drop_pct*100:.0f}% to "
                    f"{next_val:,.0f} on {events[peak_idx+1].event_date} — "
                    f"possible value inflation followed by correction"
                ),
                severity=severity,
            ))
        return flags

    # ── Pass 2 rules: cross-type (Task 3) ────────────────────────────────────

    def _check_payslip_itr_contradiction(
        self, events: list[VelocityEvent]
    ) -> list[VelocityFlag]:
        """
        PAYSLIP_ITR_CONTRADICTION
        --------------------------
        Compare salary_credit events (from payslips) against income_filing events
        (from ITR). For each ITR filing, find payslips from the same period and
        check whether monthly_gross * 12 is consistent with gross_total_income.

        Real-world fraud pattern:
          Applicant submits fabricated payslips inflating monthly salary, while
          the ITR (harder to fake, filed with the government) shows much lower income.
          OR: fabricated ITR inflating annual income, payslip contradicts it.

        event_type mapping (from VelocityEvent docstring in entities.py):
          "salary_credit"  → value = monthly_gross  (from payslip)
          "income_filing"  → value = gross_total_income (from ITR, annual)
        """
        flags = []

        salary_events  = sorted(
            [e for e in events if e.event_type == "salary_credit"],
            key=lambda e: e.event_date,
        )
        itr_events     = sorted(
            [e for e in events if e.event_type == "income_filing"],
            key=lambda e: e.event_date,
        )

        if not salary_events or not itr_events:
            return flags   # need both types to compare

        # For each ITR filing, find salary events from the same calendar year
        for itr_ev in itr_events:
            itr_date  = _safe_date(itr_ev.event_date)
            itr_year  = itr_date.year
            itr_income = itr_ev.value   # annual gross declared to Income Tax dept

            # Collect salary credits within the same assessment year
            # ITR for FY 2023-24 covers April 2023 – March 2024
            year_start = date(itr_year - 1, 4, 1)   # April of previous year
            year_end   = date(itr_year,     3, 31)   # March of filing year

            period_salaries = [
                e for e in salary_events
                if year_start <= _safe_date(e.event_date) <= year_end
            ]

            if not period_salaries:
                continue

            # Use median monthly gross (robust to one inflated slip)
            monthly_values  = [e.value for e in period_salaries]
            median_monthly  = statistics.median(monthly_values)
            implied_annual  = median_monthly * 12

            if itr_income <= 0:
                continue

            gap_pct = abs(implied_annual - itr_income) / itr_income

            if gap_pct > PAYSLIP_ITR_TOLERANCE:
                # Determine which direction the fraud likely is
                if implied_annual > itr_income:
                    direction = (
                        f"Payslips imply ₹{implied_annual:,.0f}/yr "
                        f"but ITR declares only ₹{itr_income:,.0f} — "
                        f"payslips may be inflated ({gap_pct*100:.0f}% gap)"
                    )
                else:
                    direction = (
                        f"ITR declares ₹{itr_income:,.0f}/yr "
                        f"but payslips imply only ₹{implied_annual:,.0f} — "
                        f"ITR income may be fabricated ({gap_pct*100:.0f}% gap)"
                    )

                severity = min(1.0, gap_pct / (PAYSLIP_ITR_TOLERANCE * 4) + 0.4)
                flags.append(VelocityFlag(
                    rule="PAYSLIP_ITR_CONTRADICTION",
                    event=itr_ev,
                    detail=direction,
                    severity=severity,
                ))

        return flags

    def _check_bank_round_trip(
        self, events: list[VelocityEvent]
    ) -> list[VelocityFlag]:
        """
        BANK_ROUND_TRIP
        ---------------
        Detects balance window-dressing: a large credit appears in the bank
        statement shortly before a loan application, then the balance drops
        sharply within weeks after — money was borrowed/transferred in to
        inflate the apparent balance, then returned.

        event_type mapping:
          "large_credit"     → value = credit amount  (from bank statement)
          "closing_balance"  → value = balance at statement end
          "loan_application" → value = loan amount requested (marker event)

        Detection logic:
          1. Find a loan_application event (anchor point).
          2. Look back ROUND_TRIP_WINDOW_DAYS for large_credit events >= ₹1L.
          3. Look forward ROUND_TRIP_DROP_WINDOW days for a closing_balance
             that has dropped >= 60% of that credit amount.
          4. If found → BANK_ROUND_TRIP flag.

        Falls back gracefully if no loan_application event exists:
          Looks for large_credit followed by proportional closing_balance drop
          within the combined window, without needing an anchor.
        """
        flags = []

        credit_events  = sorted(
            [e for e in events if e.event_type == "large_credit"
             and e.value >= ROUND_TRIP_MIN_AMOUNT],
            key=lambda e: e.event_date,
        )
        balance_events = sorted(
            [e for e in events if e.event_type == "closing_balance"],
            key=lambda e: e.event_date,
        )
        loan_events    = sorted(
            [e for e in events if e.event_type == "loan_application"],
            key=lambda e: e.event_date,
        )

        if not credit_events or not balance_events:
            return flags

        def _to_date(ev: VelocityEvent) -> date:
            return _safe_date(ev.event_date)

        # ── Path A: anchor on loan_application ───────────────────────────────
        if loan_events:
            for loan_ev in loan_events:
                loan_date = _to_date(loan_ev)

                # Credits in the window before loan application
                pre_credits = [
                    c for c in credit_events
                    if 0 <= (loan_date - _to_date(c)).days <= ROUND_TRIP_WINDOW_DAYS
                ]
                if not pre_credits:
                    continue

                largest_credit    = max(pre_credits, key=lambda e: e.value)
                largest_credit_dt = _to_date(largest_credit)

                # Balances after the loan application
                post_balances = [
                    b for b in balance_events
                    if 0 < (_to_date(b) - loan_date).days <= ROUND_TRIP_DROP_WINDOW
                ]
                if not post_balances:
                    continue

                # Check if balance dropped by >= 60% of the large credit
                min_balance    = min(b.value for b in post_balances)
                credit_amount  = largest_credit.value
                required_drop  = credit_amount * ROUND_TRIP_DROP_PCT

                # Approximate pre-credit balance: earliest balance before the credit
                pre_balances   = [
                    b for b in balance_events if _to_date(b) < largest_credit_dt
                ]
                baseline_bal   = pre_balances[-1].value if pre_balances else 0.0
                apparent_peak  = baseline_bal + credit_amount
                actual_drop    = apparent_peak - min_balance

                if actual_drop >= required_drop:
                    severity = min(1.0, actual_drop / (credit_amount + 1) * 0.8 + 0.4)
                    flags.append(VelocityFlag(
                        rule="BANK_ROUND_TRIP",
                        event=largest_credit,
                        detail=(
                            f"₹{credit_amount:,.0f} credit on {largest_credit.event_date} "
                            f"({(loan_date - largest_credit_dt).days}d before loan application) "
                            f"followed by balance drop of ₹{actual_drop:,.0f} within "
                            f"{ROUND_TRIP_DROP_WINDOW}d — possible balance window-dressing"
                        ),
                        severity=severity,
                    ))

        # ── Path B: no loan_application anchor — look for credit+drop pattern ─
        else:
            combined_window = timedelta(days=ROUND_TRIP_WINDOW_DAYS + ROUND_TRIP_DROP_WINDOW)

            for credit_ev in credit_events:
                credit_dt     = _to_date(credit_ev)
                credit_amount = credit_ev.value

                # Balances after this credit within combined window
                post_balances = [
                    b for b in balance_events
                    if 0 < (_to_date(b) - credit_dt).days <= (ROUND_TRIP_WINDOW_DAYS + ROUND_TRIP_DROP_WINDOW)
                ]
                if not post_balances:
                    continue

                min_balance   = min(b.value for b in post_balances)
                # Approximate pre-credit balance
                pre_balances  = [b for b in balance_events if _to_date(b) < credit_dt]
                baseline_bal  = pre_balances[-1].value if pre_balances else 0.0
                apparent_peak = baseline_bal + credit_amount
                actual_drop   = apparent_peak - min_balance

                if actual_drop >= credit_amount * ROUND_TRIP_DROP_PCT:
                    severity = min(1.0, actual_drop / (credit_amount + 1) * 0.7 + 0.35)
                    flags.append(VelocityFlag(
                        rule="BANK_ROUND_TRIP",
                        event=credit_ev,
                        detail=(
                            f"₹{credit_amount:,.0f} credit on {credit_ev.event_date} "
                            f"followed by balance drop of ₹{actual_drop:,.0f} within "
                            f"{ROUND_TRIP_WINDOW_DAYS + ROUND_TRIP_DROP_WINDOW}d — "
                            f"possible balance window-dressing (no loan anchor)"
                        ),
                        severity=severity,
                    ))

        return flags

    # ── Round 2 rules ──────────────────────────────────────────────────────────

    def _check_net_worth_inflation(
        self, events: list[VelocityEvent]
    ) -> list[VelocityFlag]:
        """
        NET_WORTH_INFLATION
        --------------------
        Two independent sub-checks against a CA-certified net worth certificate:

        (a) Implausible ratio: certified net worth > NET_WORTH_INCOME_RATIO_MAX
            (15x) the applicant's annual ITR income. A salaried borrower with
            15x their declared annual income in net assets, accumulated through
            legitimate means, is statistically implausible — this is the
            classic CA-certificate-for-hire pattern.

        (b) Spike between consecutive certificates: net worth jumped more than
            NET_WORTH_SPIKE_PCT (40%) between the two most recent certifications
            — a borrower's real assets don't double in a few months; this
            pattern indicates a freshly inflated certificate timed for the loan.

        event_type mapping:
          "net_worth_certified" → value = certified net worth (₹), from cert
          "income_filing"       → value = gross_total_income (₹), from ITR
                                   (reuses the same event_type as the
                                   payslip/ITR contradiction check)
        """
        flags = []

        nw_events = sorted(
            [e for e in events if e.event_type == "net_worth_certified"],
            key=lambda e: e.event_date,
        )
        itr_events = sorted(
            [e for e in events if e.event_type == "income_filing"],
            key=lambda e: e.event_date,
        )

        if not nw_events:
            return flags

        latest_nw = nw_events[-1]

        # (a) Ratio check against most recent ITR income
        if itr_events:
            latest_itr_income = itr_events[-1].value
            if latest_itr_income > 0:
                ratio = latest_nw.value / latest_itr_income
                if ratio > NET_WORTH_INCOME_RATIO_MAX:
                    severity = min(1.0, (ratio / NET_WORTH_INCOME_RATIO_MAX - 1) * 0.25 + 0.65)
                    flags.append(VelocityFlag(
                        rule="NET_WORTH_INFLATION",
                        event=latest_nw,
                        detail=(
                            f"Certified net worth ₹{latest_nw.value:,.0f} is "
                            f"{ratio:.1f}x annual ITR income ₹{latest_itr_income:,.0f} "
                            f"(plausibility ceiling: {NET_WORTH_INCOME_RATIO_MAX:.0f}x) — "
                            f"implausible accumulation, possible inflated CA certificate"
                        ),
                        severity=round(severity, 2),
                    ))

        # (b) Spike between the two most recent certificates
        if len(nw_events) >= 2:
            prev_nw, curr_nw = nw_events[-2].value, latest_nw.value
            if prev_nw > 0:
                spike_pct = (curr_nw - prev_nw) / prev_nw
                if spike_pct > NET_WORTH_SPIKE_PCT:
                    severity = min(1.0, spike_pct / (NET_WORTH_SPIKE_PCT * 3) + 0.4)
                    flags.append(VelocityFlag(
                        rule="NET_WORTH_INFLATION",
                        event=latest_nw,
                        detail=(
                            f"Net worth jumped {spike_pct*100:.0f}% between "
                            f"{nw_events[-2].event_date} (₹{prev_nw:,.0f}) and "
                            f"{latest_nw.event_date} (₹{curr_nw:,.0f}) — "
                            f"pre-application inflation pattern"
                        ),
                        severity=round(severity, 2),
                    ))

        return flags

    def _check_property_tax_value_contradiction(
        self, events: list[VelocityEvent]
    ) -> list[VelocityFlag]:
        """
        PROPERTY_TAX_VALUE_CONTRADICTION
        ----------------------------------
        Compares the municipality's assessed property value (from the tax
        receipt — a government record, harder to fake) against the declared
        market value used for loan sizing. A large divergence in either
        direction is a signal:

          - market value >> assessed value → inflated valuation to maximise
            loan amount against the same property
          - market value << assessed value → possible under-declaration to
            reduce property tax liability (less relevant to the bank, but
            still indicates document inconsistency worth flagging)

        event_type mapping:
          "property_tax_assessed_value" → value = municipal assessed value (₹)
          "property_market_value"       → value = declared market value (₹)
        """
        flags = []

        tax_events = sorted(
            [e for e in events if e.event_type == "property_tax_assessed_value"],
            key=lambda e: e.event_date,
        )
        market_events = sorted(
            [e for e in events if e.event_type == "property_market_value"],
            key=lambda e: e.event_date,
        )

        if not tax_events or not market_events:
            return flags

        latest_tax    = tax_events[-1]
        latest_market = market_events[-1]

        if latest_tax.value <= 0:
            return flags

        divergence = abs(latest_market.value - latest_tax.value) / latest_tax.value
        if divergence > PROPERTY_TAX_VALUE_DIVERGENCE_PCT:
            direction = "above" if latest_market.value > latest_tax.value else "below"
            severity  = min(1.0, divergence / (PROPERTY_TAX_VALUE_DIVERGENCE_PCT * 3) + 0.4)
            flags.append(VelocityFlag(
                rule="PROPERTY_TAX_VALUE_CONTRADICTION",
                event=latest_market,
                detail=(
                    f"Declared market value ₹{latest_market.value:,.0f} is "
                    f"{divergence*100:.0f}% {direction} the municipal assessed "
                    f"value ₹{latest_tax.value:,.0f} — "
                    + (
                        "possible inflated valuation for loan sizing"
                        if direction == "above"
                        else "possible under-declaration for tax avoidance"
                    )
                ),
                severity=round(severity, 2),
            ))

        return flags

    def _check_oc_before_approval(
        self, events: list[VelocityEvent]
    ) -> list[VelocityFlag]:
        """
        OC_BEFORE_APPROVAL
        --------------------
        An Occupancy Certificate dated before its building's Plan Approval is
        a physical impossibility — you cannot receive sign-off for occupying a
        building whose construction was never approved. Whenever this appears
        it means at least one of the two dates on the documents has been
        falsified (most commonly: a backdated OC to fast-track a sale or loan
        before construction was actually approved/completed).

        event_type mapping:
          "plan_approval_issued" → value = 1 (presence marker); event_date = approval date
          "oc_issued"            → value = 1 (presence marker); event_date = OC date
        """
        flags = []

        approval_events = [e for e in events if e.event_type == "plan_approval_issued"]
        oc_events       = [e for e in events if e.event_type == "oc_issued"]

        if not approval_events or not oc_events:
            return flags

        earliest_approval = min(approval_events, key=lambda e: e.event_date)
        earliest_oc       = min(oc_events,       key=lambda e: e.event_date)

        if earliest_oc.event_date < earliest_approval.event_date:
            flags.append(VelocityFlag(
                rule="OC_BEFORE_APPROVAL",
                event=earliest_oc,
                detail=(
                    f"OC dated {earliest_oc.event_date} is BEFORE plan approval "
                    f"dated {earliest_approval.event_date} — impossible sequence; "
                    f"at least one document date has been falsified"
                ),
                severity=OC_BEFORE_APPROVAL_SEVERITY,
            ))

        return flags

    # ── Convenience: aggregate risk level from flags ──────────────────────────

    def aggregate_risk(self, flags: list[VelocityFlag]) -> tuple[RiskLevel, float]:
        if not flags:
            return RiskLevel.LOW, 0.0
        max_sev = max(f.severity for f in flags)
        count   = len(flags)
        score   = min(1.0, max_sev * 0.7 + (count / 10) * 0.3)
        if score >= 0.8:  return RiskLevel.CRITICAL, score
        if score >= 0.6:  return RiskLevel.HIGH, score
        if score >= 0.35: return RiskLevel.MEDIUM, score
        return RiskLevel.LOW, score
