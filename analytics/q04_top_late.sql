SELECT f.emp_id, e.full_name, d.department_name,
       COUNT(*) AS late_count, SUM(f.late_minutes) AS total_late_minutes
FROM fact_attendance f
JOIN dim_employee e ON f.emp_id = e.emp_id
JOIN dim_department d ON f.dept_id = d.dept_id
WHERE f.late_minutes > 0
GROUP BY f.emp_id, e.full_name, d.department_name
ORDER BY late_count DESC, total_late_minutes DESC LIMIT 10;