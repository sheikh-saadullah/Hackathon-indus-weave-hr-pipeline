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