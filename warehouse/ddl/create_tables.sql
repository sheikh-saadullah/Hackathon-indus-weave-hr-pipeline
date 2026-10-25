CREATE TABLE sqlite_sequence(name,seq);

CREATE TABLE dim_department (
            dept_id TEXT PRIMARY KEY,
            department_name TEXT,
            plant TEXT
        );

CREATE TABLE dim_shift (
            shift_code TEXT PRIMARY KEY,
            name TEXT,
            start_time TEXT,
            end_time TEXT,
            crosses_midnight TEXT,
            grace_minutes TEXT
        );

CREATE TABLE dim_employee (
            emp_id TEXT PRIMARY KEY,
            full_name TEXT,
            gender TEXT,
            hire_date TEXT,
            separation_date TEXT,
            plant TEXT
        , valid_from TEXT, valid_to TEXT, is_current INTEGER DEFAULT 1);

CREATE TABLE dim_date (
            date_key TEXT PRIMARY KEY,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            weekday TEXT,
            is_weekend INTEGER
        );

CREATE TABLE fact_attendance (
            emp_id TEXT,
            work_date TEXT,
            shift_code TEXT,
            status TEXT,
            check_in TEXT,
            check_out TEXT,
            worked_hours REAL,
            late_minutes REAL,
            early_minutes REAL,
            overtime_hours REAL
        );

CREATE TABLE cfo_findings (
            finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            metric_description TEXT,
            metric_value TEXT,
            recommendation TEXT
        );

CREATE TABLE fact_leave_day (emp_id TEXT, leave_date TEXT, leave_type TEXT, leave_days REAL);

CREATE TABLE fact_overtime_approved (emp_id TEXT, dept_id TEXT, shift_date TEXT, ot_hours REAL, status TEXT);

CREATE TABLE fact_payroll_line (emp_id TEXT, dept_id TEXT, month TEXT, component TEXT, amount REAL);

CREATE TABLE dq_results (check_name TEXT, check_category TEXT, expected TEXT, actual TEXT, status TEXT, run_at TEXT);