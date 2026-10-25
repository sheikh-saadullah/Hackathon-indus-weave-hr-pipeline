SELECT substr(f.work_date, 1, 7) AS month, d.plant, d.department_name,
       COUNT(DISTINCT f.emp_id) AS headcount
FROM fact_attendance f
JOIN dim_department d ON f.dept_id = d.dept_id
GROUP BY month, d.plant, d.department_name
ORDER BY month, d.plant, d.department_name;