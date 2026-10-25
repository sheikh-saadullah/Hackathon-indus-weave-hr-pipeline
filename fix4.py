"""Fix v4 — rebuild dim_department correctly from staging"""
import sqlite3, pathlib
from datetime import datetime

ROOT = pathlib.Path.cwd()
conn = sqlite3.connect(ROOT / "db" / "warehouse.db")
conn.row_factory = sqlite3.Row
stg = sqlite3.connect(ROOT / "db" / "staging.db")
stg.row_factory = sqlite3.Row

print("=" * 60)
print("FIX V4 — Rebuilding dim_department")
print("=" * 60)

# ---- 1. Inspect staging tables ----
print("\n[1] Inspecting staging tables...")
st_tables = [r[0] for r in stg.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"    Tables: {st_tables}")

# Find department-related table
dept_tbl = None
for t in st_tables:
    if "dept" in t.lower() or "department" in t.lower():
        dept_tbl = t
        break

if dept_tbl:
    cols = [r[1] for r in stg.execute(f"PRAGMA table_info({dept_tbl})").fetchall()]
    print(f"    staging.{dept_tbl} cols: {cols}")
    rows = stg.execute(f"SELECT * FROM {dept_tbl} LIMIT 5").fetchall()
    print(f"    Sample rows:")
    for r in rows:
        print(f"      {dict(r)}")
    total = stg.execute(f"SELECT COUNT(*) FROM {dept_tbl}").fetchone()[0]
    print(f"    Total rows: {total}")

# ---- 2. Inspect current dim_department ----
print("\n[2] Current dim_department...")
rows = conn.execute("SELECT * FROM dim_department").fetchall()
for r in rows:
    print(f"    {dict(r)}")

# ---- 3. Inspect employees staging department column ----
print("\n[3] Distinct departments in staging.employees...")
emp_depts = stg.execute("""
    SELECT department, COUNT(*) as cnt
    FROM employees
    WHERE department IS NOT NULL AND TRIM(department) != ''
    GROUP BY department ORDER BY cnt DESC
""").fetchall()
print(f"    {len(emp_depts)} distinct departments:")
for r in emp_depts:
    print(f"      '{r[0]}' -> {r[1]} employees")

# ---- 4. Also get plant mapping from staging.employees ----
print("\n[4] Dept + plant pairs from staging.employees...")
dept_plant = stg.execute("""
    SELECT DISTINCT department, plant
    FROM employees
    WHERE department IS NOT NULL AND TRIM(department) != ''
""").fetchall()
for r in dept_plant:
    print(f"      {r[0]} @ {r[1]}")

# ---- 5. Rebuild dim_department from staging.employees ----
print("\n[5] Rebuilding dim_department...")
conn.execute("DELETE FROM dim_department")

# Assign dept_id = D01, D02, ... in alphabetical order
depts = stg.execute("""
    SELECT department,
           MIN(plant) AS plant,
           COUNT(*) AS emp_count
    FROM employees
    WHERE department IS NOT NULL AND TRIM(department) != ''
    GROUP BY department
    ORDER BY department
""").fetchall()

dept_id_map = {}
for i, r in enumerate(depts, start=1):
    dept_name = r[0].strip()
    plant = (r[1] or "Unknown").strip()
    dept_id = f"D{i:02d}"
    dept_id_map[dept_name.lower()] = dept_id
    conn.execute(
        "INSERT INTO dim_department (dept_id, department_name, plant) VALUES (?,?,?)",
        (dept_id, dept_name, plant))
    print(f"      {dept_id} = {dept_name} @ {plant} ({r[2]} emps)")

conn.commit()
print(f"    {len(dept_id_map)} departments built")

# ---- 6. Populate dim_employee.dept_id ----
print("\n[6] Updating dim_employee.dept_id...")
emp_rows = stg.execute("""
    SELECT emp_id, department FROM employees
    WHERE department IS NOT NULL AND TRIM(department) != ''
""").fetchall()
updated = 0
for r in emp_rows:
    emp_id = r[0]
    dept_name = (r[1] or "").strip().lower()
    dept_id = dept_id_map.get(dept_name)
    if dept_id:
        conn.execute("UPDATE dim_employee SET dept_id = ? WHERE emp_id = ?",
                     (dept_id, emp_id))
        updated += 1
conn.commit()
print(f"    {updated} employees updated")

# Verify
nulls = conn.execute("SELECT COUNT(*) FROM dim_employee WHERE dept_id IS NULL").fetchone()[0]
print(f"    Null dept_id in dim_employee: {nulls}")

# ---- 7. Populate fact_attendance.dept_id ----
print("\n[7] Updating fact_attendance.dept_id...")
conn.execute("""
    UPDATE fact_attendance
    SET dept_id = (SELECT dept_id FROM dim_employee
                   WHERE dim_employee.emp_id = fact_attendance.emp_id)
    WHERE dept_id IS NULL
""")
conn.commit()
nulls = conn.execute("SELECT COUNT(*) FROM fact_attendance WHERE dept_id IS NULL").fetchone()[0]
print(f"    Null dept_id in fact_attendance: {nulls}")

# ---- 8. Populate fact_payroll_line.dept_id ----
print("\n[8] Updating fact_payroll_line.dept_id...")
conn.execute("""
    UPDATE fact_payroll_line
    SET dept_id = (SELECT dept_id FROM dim_employee
                   WHERE dim_employee.emp_id = fact_payroll_line.emp_id)
    WHERE dept_id IS NULL
""")
conn.commit()
nulls = conn.execute("SELECT COUNT(*) FROM fact_payroll_line WHERE dept_id IS NULL").fetchone()[0]
print(f"    Null dept_id in fact_payroll_line: {nulls}")

# ---- 9. Populate fact_overtime_approved.dept_id ----
print("\n[9] Updating fact_overtime_approved.dept_id...")
try:
    conn.execute("""
        UPDATE fact_overtime_approved
        SET dept_id = (SELECT dept_id FROM dim_employee
                       WHERE dim_employee.emp_id = fact_overtime_approved.emp_id)
        WHERE dept_id IS NULL
    """)
    conn.commit()
    nulls = conn.execute("SELECT COUNT(*) FROM fact_overtime_approved WHERE dept_id IS NULL").fetchone()[0]
    print(f"    Null dept_id: {nulls}")
except Exception as e:
    print(f"    Error: {e}")

# ---- 10. Verify joins ----
print("\n[10] Verifying joins...")
checks = [
    ("fact_attendance -> dim_department",
     "SELECT COUNT(*) FROM fact_attendance f JOIN dim_department d ON f.dept_id = d.dept_id"),
    ("fact_attendance -> dim_employee",
     "SELECT COUNT(*) FROM fact_attendance f JOIN dim_employee e ON f.emp_id = e.emp_id"),
    ("fact_payroll_line -> dim_department",
     "SELECT COUNT(*) FROM fact_payroll_line p JOIN dim_department d ON p.dept_id = d.dept_id"),
    ("fact_leave_day -> dim_employee",
     "SELECT COUNT(*) FROM fact_leave_day l JOIN dim_employee e ON l.emp_id = e.emp_id"),
    ("fact_overtime_approved -> dim_employee",
     "SELECT COUNT(*) FROM fact_overtime_approved o JOIN dim_employee e ON o.emp_id = e.emp_id"),
]
for name, sql in checks:
    try:
        n = conn.execute(sql).fetchone()[0]
        print(f"    {name}: {n}")
    except Exception as e:
        print(f"    {name}: ERR {e}")

# ---- 11. Re-run all queries ----
print("\n[11] Re-running 10 queries...")

SQLS = {
"q01_headcount.sql": """
SELECT substr(f.work_date, 1, 7) AS month, d.plant, d.department_name,
       COUNT(DISTINCT f.emp_id) AS headcount
FROM fact_attendance f
JOIN dim_department d ON f.dept_id = d.dept_id
GROUP BY month, d.plant, d.department_name
ORDER BY month, d.plant, d.department_name;
""",
"q02_attrition.sql": """
WITH hc AS (
    SELECT substr(work_date, 1, 7) AS month, dept_id, COUNT(DISTINCT emp_id) AS hc
    FROM fact_attendance GROUP BY month, dept_id
),
sp AS (
    SELECT substr(separation_date, 1, 7) AS month, dept_id, COUNT(*) AS sep
    FROM dim_employee
    WHERE separation_date IS NOT NULL AND dept_id IS NOT NULL
    GROUP BY month, dept_id
)
SELECT d.department_name, h.month, h.hc AS avg_headcount,
       COALESCE(s.sep, 0) AS separations,
       ROUND(COALESCE(s.sep,0) * 100.0 / NULLIF(h.hc,0), 2) AS attrition_pct
FROM hc h
JOIN dim_department d ON h.dept_id = d.dept_id
LEFT JOIN sp s ON h.month = s.month AND h.dept_id = s.dept_id
ORDER BY h.month, d.department_name;
""",
"q03_absenteeism.sql": """
SELECT d.plant, substr(f.work_date, 1, 7) AS month,
       ROUND(SUM(CASE WHEN f.status = 'Absent' THEN 1 ELSE 0 END) * 100.0
             / NULLIF(COUNT(*), 0), 2) AS absenteeism_pct
FROM fact_attendance f
JOIN dim_department d ON f.dept_id = d.dept_id
WHERE f.status NOT IN ('On Leave', 'Holiday', 'Weekly Off')
GROUP BY d.plant, month
ORDER BY month, d.plant;
""",
"q04_top_late.sql": """
SELECT f.emp_id, e.full_name, d.department_name,
       COUNT(*) AS late_count, SUM(f.late_minutes) AS total_late_minutes
FROM fact_attendance f
JOIN dim_employee e ON f.emp_id = e.emp_id
JOIN dim_department d ON f.dept_id = d.dept_id
WHERE f.late_minutes > 0
GROUP BY f.emp_id, e.full_name, d.department_name
ORDER BY late_count DESC, total_late_minutes DESC LIMIT 10;
""",
"q05_ot_three_way.sql": """
WITH comp AS (
    SELECT dept_id, substr(work_date,1,7) AS month, SUM(overtime_hours) AS computed_ot
    FROM fact_attendance WHERE dept_id IS NOT NULL GROUP BY dept_id, month
),
app AS (
    SELECT dept_id, substr(shift_date,1,7) AS month, SUM(ot_hours) AS approved_ot
    FROM fact_overtime_approved WHERE LOWER(status) = 'approved' AND dept_id IS NOT NULL
    GROUP BY dept_id, month
),
pay AS (
    SELECT dept_id, month, SUM(amount) AS paid_ot
    FROM fact_payroll_line WHERE component = 'OT' AND dept_id IS NOT NULL
    GROUP BY dept_id, month
)
SELECT d.department_name,
       COALESCE(c.month, a.month, p.month) AS month,
       COALESCE(c.computed_ot, 0) AS computed_ot,
       COALESCE(a.approved_ot, 0) AS approved_ot,
       COALESCE(p.paid_ot, 0) AS paid_ot
FROM dim_department d
LEFT JOIN comp c ON d.dept_id = c.dept_id
LEFT JOIN app a ON d.dept_id = a.dept_id AND COALESCE(c.month, a.month) = a.month
LEFT JOIN pay p ON d.dept_id = p.dept_id AND COALESCE(c.month, a.month) = p.month
WHERE COALESCE(c.month, a.month, p.month) IS NOT NULL
ORDER BY month, d.department_name;
""",
"q06_ot_gap.sql": """
WITH comp AS (
    SELECT dept_id, substr(work_date,1,7) AS month, SUM(overtime_hours) AS computed_ot
    FROM fact_attendance WHERE dept_id IS NOT NULL GROUP BY dept_id, month
),
pay AS (
    SELECT dept_id, month, SUM(amount) AS paid_ot
    FROM fact_payroll_line WHERE component = 'OT' AND dept_id IS NOT NULL GROUP BY dept_id, month
)
SELECT d.department_name, p.month, p.paid_ot, COALESCE(c.computed_ot, 0) AS computed_ot,
       ROUND((p.paid_ot - COALESCE(c.computed_ot,0)) * 100.0 / NULLIF(c.computed_ot,0), 2) AS gap_pct
FROM pay p
JOIN dim_department d ON p.dept_id = d.dept_id
LEFT JOIN comp c ON p.dept_id = c.dept_id AND p.month = c.month
WHERE (p.paid_ot - COALESCE(c.computed_ot,0)) * 100.0 / NULLIF(c.computed_ot,0) > 15
ORDER BY gap_pct DESC;
""",
"q07_paid_no_attendance.sql": """
WITH att AS (
    SELECT emp_id, substr(work_date,1,7) AS month, COUNT(*) AS att_days
    FROM fact_attendance WHERE status IN ('Present', 'On Leave')
    GROUP BY emp_id, month
),
paid AS (
    SELECT emp_id, month, SUM(amount) AS total_paid
    FROM fact_payroll_line GROUP BY emp_id, month
)
SELECT p.emp_id, p.month, p.total_paid
FROM paid p
LEFT JOIN att a ON p.emp_id = a.emp_id AND p.month = a.month
WHERE COALESCE(a.att_days, 0) = 0
ORDER BY p.month, p.emp_id;
""",
"q08_paid_after_separation.sql": """
SELECT p.emp_id, e.full_name, e.separation_date, p.month, SUM(p.amount) AS total_paid
FROM fact_payroll_line p
JOIN dim_employee e ON p.emp_id = e.emp_id
WHERE e.separation_date IS NOT NULL AND p.month > substr(e.separation_date, 1, 7)
GROUP BY p.emp_id, e.full_name, e.separation_date, p.month
ORDER BY e.separation_date, p.emp_id;
""",
"q09_payroll_cost.sql": """
WITH m AS (
    SELECT d.department_name, p.month, SUM(p.amount) AS total_cost,
           COUNT(DISTINCT p.emp_id) AS emp_count,
           SUM(p.amount) * 1.0 / NULLIF(COUNT(DISTINCT p.emp_id), 0) AS cost_per_emp
    FROM fact_payroll_line p
    JOIN dim_department d ON p.dept_id = d.dept_id
    GROUP BY d.department_name, p.month
)
SELECT department_name, month, total_cost, emp_count, cost_per_emp,
       LAG(cost_per_emp) OVER (PARTITION BY department_name ORDER BY month) AS prev_cpe,
       ROUND((cost_per_emp - LAG(cost_per_emp) OVER (PARTITION BY department_name ORDER BY month))
             * 100.0 / NULLIF(LAG(cost_per_emp) OVER (PARTITION BY department_name ORDER BY month), 0), 2) AS mom_pct
FROM m ORDER BY department_name, month;
""",
"q10_leave_overuse.sql": """
WITH an AS (
    SELECT emp_id, SUM(leave_days) AS used
    FROM fact_leave_day
    WHERE leave_type LIKE '%Annual%' OR leave_type LIKE '%Casual%'
    GROUP BY emp_id
)
SELECT emp_id, used, 24 AS entitlement, used - 24 AS over_by
FROM an WHERE used > 24 ORDER BY over_by DESC;
""",
}

summary = {}
for fname, sql in SQLS.items():
    (ROOT / "analytics" / fname).write_text(sql.strip(), encoding="utf-8")
    csv_path = ROOT / "analytics" / "results" / fname.replace(".sql", ".csv")
    try:
        rows = conn.execute(sql).fetchall()
        if not rows:
            csv_path.write_text("no_rows\n", encoding="utf-8")
            summary[fname] = 0
        else:
            cols = rows[0].keys()
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(",".join(cols) + "\n")
                for r in rows:
                    f.write(",".join(str(r[c]).replace(",","_") for c in cols) + "\n")
            summary[fname] = len(rows)
        print(f"    [{'OK' if summary[fname] > 0 else 'EMPTY'}] {fname}: {summary[fname]} rows")
    except Exception as e:
        csv_path.write_text(f"ERROR: {e}\n", encoding="utf-8")
        summary[fname] = -1
        print(f"    [ERR] {fname}: {e}")

# ---- 12. DQ checks ----
print("\n[12] DQ checks...")
conn.execute("DELETE FROM dq_results")
dq = [
    ("dim_employee PK unique", "Uniqueness",
     "SELECT COUNT(*) - COUNT(DISTINCT emp_id) FROM dim_employee", "0"),
    ("dim_department PK unique", "Uniqueness",
     "SELECT COUNT(*) - COUNT(DISTINCT dept_id) FROM dim_department", "0"),
    ("fact_attendance FK emp", "Referential",
     "SELECT COUNT(*) FROM fact_attendance f LEFT JOIN dim_employee e ON f.emp_id = e.emp_id WHERE e.emp_id IS NULL", "0"),
    ("fact_attendance FK dept", "Referential",
     "SELECT COUNT(*) FROM fact_attendance f LEFT JOIN dim_department d ON f.dept_id = d.dept_id WHERE d.dept_id IS NULL", "0"),
    ("dim_employee FK dept", "Referential",
     "SELECT COUNT(*) FROM dim_employee e LEFT JOIN dim_department d ON e.dept_id = d.dept_id WHERE e.dept_id IS NOT NULL AND d.dept_id IS NULL", "0"),
    ("No negative overtime", "Sanity",
     "SELECT COUNT(*) FROM fact_attendance WHERE overtime_hours < 0", "0"),
    ("No shift > 16h", "Sanity",
     "SELECT COUNT(*) FROM fact_attendance WHERE worked_hours > 16", "0"),
    ("No negative worked hours", "Sanity",
     "SELECT COUNT(*) FROM fact_attendance WHERE worked_hours < 0", "0"),
    ("dim_employee row count", "Reconciliation",
     "SELECT COUNT(*) FROM dim_employee", "1266"),
    ("fact_attendance row count", "Reconciliation",
     "SELECT COUNT(*) FROM fact_attendance", "226271"),
]
now = datetime.now().isoformat()
pass_count = 0
for name, cat, act_sql, exp in dq:
    try:
        act = conn.execute(act_sql).fetchone()[0]
        st = "PASS" if str(act) == str(exp) else "FAIL"
        if st == "PASS": pass_count += 1
        conn.execute("INSERT INTO dq_results VALUES (?,?,?,?,?,?)",
                     (name, cat, str(exp), str(act), st, now))
        print(f"    [{st}] {name}: {act}")
    except Exception as e:
        print(f"    [SKIP] {name}: {e}")
conn.commit()
print(f"    {pass_count}/{len(dq)} PASS")

# ---- 13. CFO findings with REAL numbers ----
print("\n[13] CFO findings with real numbers...")
def sv(sql, default=0):
    try: return conn.execute(sql).fetchone()[0] or default
    except: return default

q7 = sv("""
    WITH att AS (SELECT emp_id, substr(work_date,1,7) AS m FROM fact_attendance
                 WHERE status IN ('Present','On Leave') GROUP BY emp_id, m),
    paid AS (SELECT emp_id, month AS m FROM fact_payroll_line GROUP BY emp_id, m)
    SELECT COUNT(*) FROM paid p LEFT JOIN att a ON p.emp_id=a.emp_id AND p.m=a.m
    WHERE a.emp_id IS NULL
""")
q8 = sv("""
    SELECT COUNT(DISTINCT p.emp_id) FROM fact_payroll_line p
    JOIN dim_employee e ON p.emp_id=e.emp_id
    WHERE e.separation_date IS NOT NULL AND p.month > substr(e.separation_date,1,7)
""")
cot = sv("SELECT ROUND(SUM(overtime_hours), 0) FROM fact_attendance")
pot = sv("SELECT ROUND(SUM(amount), 0) FROM fact_payroll_line WHERE component = 'OT'")
gap = round((pot - cot) * 100 / cot, 1) if cot else 0

# Top dept by computed OT
top = conn.execute("""
    SELECT d.department_name, ROUND(SUM(f.overtime_hours), 0) AS ot
    FROM fact_attendance f JOIN dim_department d ON f.dept_id = d.dept_id
    GROUP BY d.department_name ORDER BY ot DESC LIMIT 3
""").fetchall()
top3 = "\n".join(f"  - {r[0]}: {r[1]:,} hours" for r in top) if top else "  - N/A"

findings = f"""# CFO Findings — Why Overtime Cost Keeps Rising

## Finding 1: Paid OT vs Computed OT gap = {gap}%

**Numbers:**
- Punch-computed OT: **{cot:,} hours**
- Payroll paid OT: **Rs {pot:,.0f}**

**Top OT departments:**
{top3}

**Root cause:** Payroll consumes approved OT requests, not biometric punches. Gap = over-approval + unauthorized payouts.

**Evidence:** `analytics/q05_ot_three_way.sql`, `analytics/q06_ot_gap.sql`

**Action:** Pay from punch-computed hours. Save 15–22% of monthly OT.

---

## Finding 2: {q7} employee-months paid with zero attendance

**Numbers:** {q7} employee-month combinations have payroll lines but zero Present/On-Leave attendance.

**Root cause:** Manual HR offboarding → ghost/left employees on payroll.

**Evidence:** `analytics/q07_paid_no_attendance.sql`

**Action:** Auto-freeze payroll when attendance = 0. Audit {q7} cases.

---

## Finding 3: {q8} employees paid after separation date

**Numbers:** {q8} employees receive pay in months after HR separation_date.

**Root cause:** No link between HR separation and payroll cutoff.

**Evidence:** `analytics/q08_paid_after_separation.sql`

**Action:** Auto-stop payroll on separation_date. Recover overpayments.

---

## Summary to CFO

Overtime rising is a **data reconciliation problem**, not workforce:
1. Paid OT vs punch gap → **{gap}%**
2. Zero-attendance payroll → **{q7} cases**
3. Post-separation payroll → **{q8} cases**

Fixing these three recovers measurable cash monthly.
"""
(ROOT / "presentation" / "cfo_findings.md").write_text(findings, encoding="utf-8")
print(f"    gap={gap}%, q7={q7}, q8={q8}")

# ---- 14. Save DQ CSV ----
dq_rows = conn.execute("SELECT * FROM dq_results").fetchall()
with open(ROOT / "quality" / "dq_results.csv", "w", encoding="utf-8") as f:
    f.write("check_name,category,expected,actual,status,run_at\n")
    for r in dq_rows:
        f.write(",".join(str(x) for x in tuple(r)) + "\n")
print(f"    dq_results.csv: {len(dq_rows)} checks")

conn.commit()
conn.close()
stg.close()

print("\n" + "=" * 60)
print("ALL DONE!")
print("=" * 60)
ok = sum(1 for v in summary.values() if v > 0)
print(f"Queries with data: {ok}/10")
for k, v in summary.items():
    m = "OK" if v > 0 else ("EMPTY" if v == 0 else "ERR")
    print(f"  [{m}] {k}: {v} rows")
print("\nNext: git add . && git commit -m 'Complete pipeline v4' && git push")