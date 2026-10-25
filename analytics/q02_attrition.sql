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