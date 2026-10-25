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