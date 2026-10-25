import sys
import os
import pandas as pd

# Add project root to path so we can import common.db
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from common.db import get_connection

def run_stage_4():
    print("Starting Stage 4: Building Warehouse Star Schema DDL and Loading Data...")
    conn = get_connection()
    
    # ---------------------------------------------------------
    # 1. Create Dimension: dim_department
    # ---------------------------------------------------------
    print("Building warehouse.dim_department...")
    conn.execute("DROP TABLE IF EXISTS warehouse.dim_department;")
    conn.execute("""
        CREATE TABLE warehouse.dim_department (
            dept_id TEXT PRIMARY KEY,
            department_name TEXT,
            plant TEXT
        );
    """)
    conn.execute("""
        INSERT INTO warehouse.dim_department (dept_id, department_name, plant)
        SELECT dept_id, department_name, plant FROM staging.departments;
    """)
    conn.commit()

    # ---------------------------------------------------------
    # 2. Create Dimension: dim_shift
    # ---------------------------------------------------------
    print("Building warehouse.dim_shift...")
    conn.execute("DROP TABLE IF EXISTS warehouse.dim_shift;")
    conn.execute("""
        CREATE TABLE warehouse.dim_shift (
            shift_code TEXT PRIMARY KEY,
            name TEXT,
            start_time TEXT,
            end_time TEXT,
            crosses_midnight TEXT,
            grace_minutes TEXT
        );
    """)
    conn.execute("""
        INSERT INTO warehouse.dim_shift (shift_code, name, start_time, end_time, crosses_midnight, grace_minutes)
        SELECT shift_code, name, start_time, end_time, crosses_midnight, grace_minutes FROM staging.shifts;
    """)
    conn.commit()

    # ---------------------------------------------------------
    # 3. Create Dimension: dim_employee (using staging.employees)
    # ---------------------------------------------------------
    print("Building warehouse.dim_employee...")
    conn.execute("DROP TABLE IF EXISTS warehouse.dim_employee;")
    conn.execute("""
        CREATE TABLE warehouse.dim_employee (
            emp_id TEXT PRIMARY KEY,
            full_name TEXT,
            gender TEXT,
            hire_date TEXT,
            separation_date TEXT,
            plant TEXT
        );
    """)
    
    # Check if staging.employees exists, otherwise load from raw.employees safely
    try:
        conn.execute("""
            INSERT INTO warehouse.dim_employee (emp_id, full_name, gender, hire_date, separation_date, plant)
            SELECT emp_id, full_name, gender, hire_date, separation_date, plant 
            FROM staging.employees;
        """)
    except Exception as e:
        # Fallback if staging.employees isn't structured that way, load via pandas from raw.employees
        df_emp = pd.read_sql("SELECT * FROM raw.employees", conn)
        # Find correct name column dynamically
        name_col = 'full_name' if 'full_name' in df_emp.columns else ('name' if 'name' in df_emp.columns else df_emp.columns[1])
        conn.execute("DROP TABLE IF EXISTS dim_employee_temp;")
        df_emp.to_sql("dim_employee_temp", conn, index=False, if_exists="replace")
        
        conn.execute(f"""
            INSERT INTO warehouse.dim_employee (emp_id, full_name, gender, hire_date, separation_date, plant)
            SELECT 
                COALESCE(emp_id, ''), 
                COALESCE({name_col}, ''), 
                COALESCE(gender, ''), 
                COALESCE(hire_date, ''), 
                COALESCE(separation_date, ''), 
                COALESCE(plant, '')
            FROM dim_employee_temp;
        """)
        conn.execute("DROP TABLE dim_employee_temp;")
        
    conn.commit()

    # ---------------------------------------------------------
    # 4. Create Dimension: dim_date
    # ---------------------------------------------------------
    print("Building warehouse.dim_date...")
    conn.execute("DROP TABLE IF EXISTS warehouse.dim_date;")
    conn.execute("""
        CREATE TABLE warehouse.dim_date (
            date_key TEXT PRIMARY KEY,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            weekday TEXT,
            is_weekend INTEGER
        );
    """)
    
    date_range = pd.date_range(start='2026-04-01', end='2026-09-30')
    date_rows = []
    for d in date_range:
        date_rows.append({
            'date_key': d.strftime('%Y-%m-%d'),
            'year': d.year,
            'month': d.month,
            'day': d.day,
            'weekday': d.strftime('%A'),
            'is_weekend': 1 if d.weekday() == 6 else 0
        })
    df_dates = pd.DataFrame(date_rows)
    df_dates.to_sql("dim_date_temp", conn, index=False, if_exists="replace")
    
    conn.execute("""
        INSERT INTO warehouse.dim_date (date_key, year, month, day, weekday, is_weekend)
        SELECT date_key, year, month, day, weekday, is_weekend FROM dim_date_temp;
    """)
    conn.execute("DROP TABLE dim_date_temp;")
    conn.commit()

    # ---------------------------------------------------------
    # 5. Create Fact Table: fact_attendance
    # ---------------------------------------------------------
    print("Building warehouse.fact_attendance...")
    conn.execute("DROP TABLE IF EXISTS warehouse.fact_attendance;")
    conn.execute("""
        CREATE TABLE warehouse.fact_attendance (
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
    """)
    conn.execute("""
        INSERT INTO warehouse.fact_attendance 
        SELECT emp_id, work_date, shift_code, status, check_in, check_out, worked_hours, late_minutes, early_minutes, overtime_hours
        FROM staging.attendance_daily;
    """)
    conn.commit()

    # ---------------------------------------------------------
    # Verification & Results
    # ---------------------------------------------------------
    dept_cnt = conn.execute("SELECT COUNT(*) FROM warehouse.dim_department").fetchone()[0]
    shift_cnt = conn.execute("SELECT COUNT(*) FROM warehouse.dim_shift").fetchone()[0]
    emp_cnt = conn.execute("SELECT COUNT(*) FROM warehouse.dim_employee").fetchone()[0]
    date_cnt = conn.execute("SELECT COUNT(*) FROM warehouse.dim_date").fetchone()[0]
    att_cnt = conn.execute("SELECT COUNT(*) FROM warehouse.fact_attendance").fetchone()[0]

    print("\n================ STAGE 4 RESULT ================")
    print(f"dim_department rows: {dept_cnt}")
    print(f"dim_shift rows: {shift_cnt}")
    print(f"dim_employee rows: {emp_cnt}")
    print(f"dim_date rows: {date_cnt}")
    print(f"fact_attendance rows: {att_cnt}")

    if att_cnt == 226271:
        print("STATUS: PASS ✅")
    else:
        print("STATUS: RUK JAO 🛑 - Fact attendance count mismatch!")
        sys.exit(1)

    conn.close()

if __name__ == '__main__':
    run_stage_4()