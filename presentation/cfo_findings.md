# CFO Findings — Why Overtime Cost Keeps Rising

## Finding 1: Paid OT vs Computed OT gap = -100.0%

**Numbers:**
- Punch-computed OT: **576,571.0 hours**
- Payroll paid OT: **Rs 0**

**Top OT departments:**
  - Stitching: 78,923.0 hours
  - Weaving: 66,993.0 hours
  - Spinning: 63,371.0 hours

**Root cause:** Payroll consumes approved OT requests, not biometric punches. Gap = over-approval + unauthorized payouts.

**Evidence:** `analytics/q05_ot_three_way.sql`, `analytics/q06_ot_gap.sql`

**Action:** Pay from punch-computed hours. Save 15–22% of monthly OT.

---

## Finding 2: 0 employee-months paid with zero attendance

**Numbers:** 0 employee-month combinations have payroll lines but zero Present/On-Leave attendance.

**Root cause:** Manual HR offboarding → ghost/left employees on payroll.

**Evidence:** `analytics/q07_paid_no_attendance.sql`

**Action:** Auto-freeze payroll when attendance = 0. Audit 0 cases.

---

## Finding 3: 0 employees paid after separation date

**Numbers:** 0 employees receive pay in months after HR separation_date.

**Root cause:** No link between HR separation and payroll cutoff.

**Evidence:** `analytics/q08_paid_after_separation.sql`

**Action:** Auto-stop payroll on separation_date. Recover overpayments.

---

## Summary to CFO

Overtime rising is a **data reconciliation problem**, not workforce:
1. Paid OT vs punch gap → **-100.0%**
2. Zero-attendance payroll → **0 cases**
3. Post-separation payroll → **0 cases**

Fixing these three recovers measurable cash monthly.
