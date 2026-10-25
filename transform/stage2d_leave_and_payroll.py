import sys
import os
import pandas as pd
import json
import re

# Add project root to path so we can import common.db
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from common.db import get_connection

def clean_col_names(df):
    """Helper to clean column names so they are SQL-safe."""
    df.columns = [re.sub(r'[^a-zA-Z0-9_]', '_', str(c)).strip('_') for c in df.columns]
    return df

def run_stage_2d():
    print("Starting Stage 2D: Leave Flattening, Approval Steps, Leave Days Expansion & Payroll...")
    conn = get_connection()
    
    # ---------------------------------------------------------
    # 1. Process Leave Requests (from JSON)
    # ---------------------------------------------------------
    print("Processing leave requests JSON...")
    raw_leaves_cursor = conn.execute("SELECT raw_json FROM raw.leave_requests").fetchall()
    
    requests_list = []
    approvals_list = []
    
    for row in raw_leaves_cursor:
        data = json.loads(row[0])
        req_id = data.get('request_id')
        emp_info = data.get('employee', {})
        emp_id = emp_info.get('emp_id')
        plant = emp_info.get('plant')
        
        leave_info = data.get('leave', {})
        leave_type = leave_info.get('type')
        from_date = leave_info.get('from')
        to_date = leave_info.get('to')
        days_requested = leave_info.get('days_requested')
        
        submitted_at = data.get('submitted_at')
        cancelled_at = data.get('cancelled_at')
        
        requests_list.append({
            'request_id': req_id,
            'emp_id': emp_id,
            'plant': plant,
            'leave_type': leave_type,
            'from_date': from_date,
            'to_date': to_date,
            'days_requested': days_requested,
            'submitted_at': submitted_at,
            'cancelled_at': cancelled_at
        })
        
        # Approvals steps nesting
        for app in data.get('approvals', []):
            approvals_list.append({
                'request_id': req_id,
                'step': app.get('step'),
                'approver_role': app.get('approver_role'),
                'approver_id': app.get('approver_id'),
                'action': app.get('action'),
                'acted_at': app.get('acted_at')
            })
            
    df_requests = pd.DataFrame(requests_list)
    df_approvals = pd.DataFrame(approvals_list)
    
    conn.execute("DROP TABLE IF EXISTS staging.leave_requests;")
    conn.execute("""
        CREATE TABLE staging.leave_requests (
            request_id TEXT,
            emp_id TEXT,
            plant TEXT,
            leave_type TEXT,
            from_date TEXT,
            to_date TEXT,
            days_requested REAL,
            submitted_at TEXT,
            cancelled_at TEXT
        );
    """)
    for _, r in df_requests.iterrows():
        conn.execute("""
            INSERT INTO staging.leave_requests (request_id, emp_id, plant, leave_type, from_date, to_date, days_requested, submitted_at, cancelled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (r['request_id'], r['emp_id'], r['plant'], r['leave_type'], r['from_date'], r['to_date'], r['days_requested'], r['submitted_at'], r['cancelled_at']))
    conn.commit()
    
    conn.execute("DROP TABLE IF EXISTS staging.leave_approvals;")
    conn.execute("""
        CREATE TABLE staging.leave_approvals (
            request_id TEXT,
            step TEXT,
            approver_role TEXT,
            approver_id TEXT,
            action TEXT,
            acted_at TEXT
        );
    """)
    for _, a in df_approvals.iterrows():
        conn.execute("""
            INSERT INTO staging.leave_approvals (request_id, step, approver_role, approver_id, action, acted_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (a['request_id'], a['step'], a['approver_role'], a['approver_id'], a['action'], a['acted_at']))
    conn.commit()
    
    # ---------------------------------------------------------
    # 2. Expand Approved Leave Days (Rule 16 & 17)
    # ---------------------------------------------------------
    print("Expanding approved leave requests into individual leave days...")
    # Rule 16: Leave counts only if BOTH approval steps (Manager then HR) are "Approved" and cancelled_at is empty.
    # Let's check approvals in df_approvals
    approval_check = df_approvals.groupby('request_id').filter(
        lambda g: len(g) == 2 and all(g['action'] == 'Approved')
    )['request_id'].unique()
    
    valid_leave_reqs = df_requests[
        (df_requests['request_id'].isin(approval_check)) & 
        (df_requests['cancelled_at'].isna() | (df_requests['cancelled_at'] == '') | (df_requests['cancelled_at'] == 'nan'))
    ].copy()
    
    # Get holidays by plant to exclude Sundays and plant holidays (Rule 17)
    holidays_df = pd.read_sql("SELECT holiday_date, plant FROM staging.holidays", conn)
    holiday_set = set(zip(holidays_df['holiday_date'], holidays_df['plant']))
    
    leave_days_list = []
    for _, r in valid_leave_reqs.iterrows():
        emp_id = r['emp_id']
        plant = r['plant']
        l_type = r['leave_type']
        
        date_range = pd.date_range(start=r['from_date'], end=r['to_date'])
        for single_date in date_range:
            d_str = single_date.strftime('%Y-%m-%d')
            is_sunday = (single_date.weekday() == 6)
            is_holiday = ((d_str, plant) in holiday_set) or ((d_str, 'All') in holiday_set)
            
            # Rule 17: Leave days = every day from..to EXCLUDING Sundays and plant holidays
            if not is_sunday and not is_holiday:
                leave_days_list.append({
                    'emp_id': emp_id,
                    'leave_date': d_str,
                    'leave_type': l_type,
                    'request_id': r['request_id']
                })
                
    df_leave_days = pd.DataFrame(leave_days_list)
    
    conn.execute("DROP TABLE IF EXISTS staging.leave_days;")
    conn.execute("""
        CREATE TABLE staging.leave_days (
            emp_id TEXT,
            leave_date TEXT,
            leave_type TEXT,
            request_id TEXT
        );
    """)
    if not df_leave_days.empty:
        for _, ld in df_leave_days.iterrows():
            conn.execute("""
                INSERT INTO staging.leave_days (emp_id, leave_date, leave_type, request_id)
                VALUES (?, ?, ?, ?)
            """, (ld['emp_id'], ld['leave_date'], ld['leave_type'], ld['request_id']))
    conn.commit()
    
    # ---------------------------------------------------------
    # 3. Process Overtime Requests
    # ---------------------------------------------------------
    print("Processing overtime requests...")
    df_ot = pd.read_sql("SELECT * FROM raw.overtime_requests", conn)
    df_ot = clean_clean_cols = clean_col_names(df_ot)
    for col in df_ot.select_dtypes(include=['object']).columns:
        df_ot[col] = df_ot[col].astype(str).str.strip()
        
    conn.execute("DROP TABLE IF EXISTS staging.overtime_requests;")
    conn.execute("""
        CREATE TABLE staging.overtime_requests (
            request_id TEXT,
            emp_id TEXT,
            shift_date TEXT,
            approved_hours REAL,
            status TEXT
        );
    """)
    for _, row in df_ot.iterrows():
        app_hrs = row.get('approved_hours')
        try:
            app_hrs = float(app_hrs) if app_hrs not in [None, '', 'nan', 'None'] else 0.0
        except:
            app_hrs = 0.0
            
        conn.execute("""
            INSERT INTO staging.overtime_requests (request_id, emp_id, shift_date, approved_hours, status)
            VALUES (?, ?, ?, ?, ?)
        """, (row.get('request_id'), row.get('emp_id'), row.get('shift_date'), app_hrs, row.get('status')))
    conn.commit()
    
    # ---------------------------------------------------------
    # 4. Process Payroll Lines
    # ---------------------------------------------------------
    print("Processing payroll lines...")
    df_pay = pd.read_sql("SELECT * FROM raw.payroll_lines", conn)
    df_pay = clean_col_names(df_pay)
    for col in df_pay.select_dtypes(include=['object']).columns:
        df_pay[col] = df_pay[col].astype(str).str.strip()
        
    conn.execute("DROP TABLE IF EXISTS staging.payroll_lines;")
    conn.execute("""
        CREATE TABLE staging.payroll_lines (
            emp_id TEXT,
            payroll_month TEXT,
            component TEXT,
            component_type TEXT,
            amount REAL,
            units REAL
        );
    """)
    for _, row in df_pay.iterrows():
        try:
            amount = float(row.get('amount')) if row.get('amount') not in [None, '', 'nan'] else 0.0
        except:
            amount = 0.0
        try:
            units = float(row.get('units')) if row.get('units') not in [None, '', 'nan'] else 0.0
        except:
            units = 0.0
            
        conn.execute("""
            INSERT INTO staging.payroll_lines (emp_id, payroll_month, component, component_type, amount, units)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (row.get('emp_id'), row.get('payroll_month'), row.get('component'), row.get('component_type'), amount, units))
    conn.commit()
    
    # ---------------------------------------------------------
    # Verification & Results
    # ---------------------------------------------------------
    req_count = conn.execute("SELECT COUNT(*) FROM staging.leave_requests").fetchone()[0]
    days_count = conn.execute("SELECT COUNT(*) FROM staging.leave_days").fetchone()[0]
    ot_count = conn.execute("SELECT COUNT(*) FROM staging.overtime_requests").fetchone()[0]
    pay_count = conn.execute("SELECT COUNT(*) FROM staging.payroll_lines").fetchone()[0]
    
    print("\n================ STAGE 2D RESULT ================")
    print(f"Leave Requests loaded: {req_count} (Expected: 5372)")
    print(f"Expanded Leave Days: {days_count}")
    print(f"Overtime Requests loaded: {ot_count} (Expected: 22098)")
    print(f"Payroll Lines loaded: {pay_count} (Expected: 53617)")
    
    if req_count == 5372 and ot_count == 22098 and pay_count == 53617:
        print("STATUS: PASS ✅")
    else:
        print("STATUS: RUK JAO 🛑 - Counts do not match expected values!")
        sys.exit(1)
        
    conn.close()

if __name__ == '__main__':
    run_stage_2d()