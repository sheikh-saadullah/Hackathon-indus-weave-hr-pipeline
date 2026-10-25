WITH an AS (
    SELECT emp_id, SUM(leave_days) AS used
    FROM fact_leave_day
    WHERE leave_type LIKE '%Annual%' OR leave_type LIKE '%Casual%'
    GROUP BY emp_id
)
SELECT emp_id, used, 24 AS entitlement, used - 24 AS over_by
FROM an WHERE used > 24 ORDER BY over_by DESC;