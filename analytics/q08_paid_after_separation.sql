SELECT p.emp_id, e.full_name, e.separation_date, p.month, SUM(p.amount) AS total_paid
FROM fact_payroll_line p
JOIN dim_employee e ON p.emp_id = e.emp_id
WHERE e.separation_date IS NOT NULL AND p.month > substr(e.separation_date, 1, 7)
GROUP BY p.emp_id, e.full_name, e.separation_date, p.month
ORDER BY e.separation_date, p.emp_id;