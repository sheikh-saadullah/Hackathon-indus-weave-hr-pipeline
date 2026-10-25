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