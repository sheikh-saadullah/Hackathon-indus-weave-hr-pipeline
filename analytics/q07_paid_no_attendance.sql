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