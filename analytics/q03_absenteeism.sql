SELECT d.plant, substr(f.work_date, 1, 7) AS month,
       ROUND(SUM(CASE WHEN f.status = 'Absent' THEN 1 ELSE 0 END) * 100.0
             / NULLIF(COUNT(*), 0), 2) AS absenteeism_pct
FROM fact_attendance f
JOIN dim_department d ON f.dept_id = d.dept_id
WHERE f.status NOT IN ('On Leave', 'Holiday', 'Weekly Off')
GROUP BY d.plant, month
ORDER BY month, d.plant;