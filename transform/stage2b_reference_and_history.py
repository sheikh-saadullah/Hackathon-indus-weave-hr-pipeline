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

def run_stage_2b():
    print("Starting Stage 2B: Reference Tables and Employment History Transformation...")
    conn = get_connection()
    
    # ---------------------------------------------------------
    # 1. Process Departments
    # ---------------------------------------------------------
    print("Processing departments...")
    df_dept = pd.read_sql("SELECT * FROM raw.departments", conn)
    df_dept = clean_col_names(df_dept)
    
    conn.execute("DROP TABLE IF EXISTS staging.departments;")
    conn.execute("""
        CREATE TABLE staging.departments (
            dept_id TEXT,
            department_name TEXT,
            plant TEXT
        );
    """)
    for _, row in df_dept.iterrows():
        conn.execute("INSERT INTO staging.departments (dept_id, department_name, plant) VALUES (?, ?, ?)",
                     (str(row.get('dept_id', '')).strip(), str(row.get('department_name', '')).strip(), str(row.get('plant', '')).strip()))
    conn.commit()
    
    # ---------------------------------------------------------
    # 2. Process Shifts (from JSON)
    # ---------------------------------------------------------
    print("Processing shifts...")
    raw_shifts_cursor = conn.execute("SELECT raw_json FROM raw.shifts").fetchall()
    shifts_list = []
    for row in raw_shifts_cursor:
        try:
            data = json.loads(row[0])
            if isinstance(data, dict):
                if 'shifts' in data:
                    shifts_list.extend(data['shifts'])
                else:
                    shifts_list.append(data)
            elif isinstance(data, list):
                shifts_list.extend(data)
        except Exception as e:
            print(f"Error parsing shift json: {e}")
            
    conn.execute("DROP TABLE IF EXISTS staging.shifts;")
    conn.execute("""
        CREATE TABLE staging.shifts (
            shift_code TEXT,
            name TEXT,
            start_time TEXT,
            end_time TEXT,
            crosses_midnight TEXT,
            grace_minutes TEXT,
            applies_to TEXT
        );
    """)
    
    for s in shifts_list:
        code = s.get('shift_code')
        name = s.get('name')
        start = s.get('start_time')
        end = s.get('end_time')
        cross = str(s.get('crosses_midnight', ''))
        
        grace = None
        for k, v in s.items():
            if 'grace' in k.lower():
                grace = v
                break
                
        applies = s.get('applies_to')
        if isinstance(applies, (list, dict)):
            applies = json.dumps(applies)
            
        conn.execute("""
            INSERT INTO staging.shifts (shift_code, name, start_time, end_time, crosses_midnight, grace_minutes, applies_to)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (str(code), str(name), str(start), str(end), cross, str(grace), str(applies)))
    conn.commit()
    
    # ---------------------------------------------------------
    # 3. Process Holidays
    # ---------------------------------------------------------
    print("Processing holidays...")
    df_holidays = pd.read_sql("SELECT * FROM raw.holidays", conn)
    df_holidays = clean_col_names(df_holidays)
    
    conn.execute("DROP TABLE IF EXISTS staging.holidays;")
    conn.execute("""
        CREATE TABLE staging.holidays (
            holiday_date TEXT,
            holiday_name TEXT,
            plant TEXT
        );
    """)
    for _, row in df_holidays.iterrows():
        conn.execute("INSERT INTO staging.holidays (holiday_date, holiday_name, plant) VALUES (?, ?, ?)",
                     (str(row.get('holiday_date', '')).strip(), str(row.get('holiday_name', '')).strip(), str(row.get('plant', '')).strip()))
    conn.commit()
    
    conn.execute("DROP TABLE IF EXISTS staging.holidays_by_plant;")
    conn.execute("""
        CREATE TABLE staging.holidays_by_plant AS
        SELECT holiday_date, holiday_name, plant 
        FROM staging.holidays;
    """)
    conn.commit()
    
    # ---------------------------------------------------------
    # 4. Process Employment History (Rule 2 & Issues Detection)
    # ---------------------------------------------------------
    print("Processing employment history and applying Rule 2...")
    df_raw_hist = pd.read_sql("SELECT * FROM raw.employment_history", conn)
    df_raw_hist = clean_col_names(df_raw_hist)
    
    # Detect Overlaps and Gaps from raw data before recomputing valid_to
    issues = []
    df_raw_hist['eff_from_dt'] = pd.to_datetime(df_raw_hist['effective_from'], errors='coerce')
    df_raw_hist['eff_to_dt'] = pd.to_datetime(df_raw_hist['effective_to'], errors='coerce')
    
    for emp_id, group in df_raw_hist.groupby('emp_id'):
        group = group.sort_values('eff_from_dt')
        group_list = group.to_dict('records')
        for i in range(len(group_list) - 1):
            curr = group_list[i]
            nxt = group_list[i+1]
            curr_end = curr['eff_to_dt']
            next_start = nxt['eff_from_dt']
            
            if pd.notna(curr_end) and pd.notna(next_start):
                if curr_end >= next_start:
                    issues.append({
                        'emp_id': emp_id, 
                        'issue_type': 'OVERLAP', 
                        'details': f"Record {i} ends on {curr['effective_to']} but next starts on {nxt['effective_from']}"
                    })
                elif (next_start - curr_end).days > 1:
                    issues.append({
                        'emp_id': emp_id, 
                        'issue_type': 'GAP', 
                        'details': f"Gap between record {i} and {i+1}"
                    })

    conn.execute("DROP TABLE IF EXISTS staging.employment_history_issues;")
    conn.execute("""
        CREATE TABLE staging.employment_history_issues (
            emp_id TEXT,
            issue_type TEXT,
            details TEXT
        );
    """)
    for iss in issues:
        conn.execute("INSERT INTO staging.employment_history_issues (emp_id, issue_type, details) VALUES (?, ?, ?)",
                     (iss['emp_id'], iss['issue_type'], iss['details']))
    conn.commit()

    # Now apply Rule 2 for clean staging.employment_history
    df_hist = df_raw_hist.copy()
    df_hist['effective_from'] = pd.to_datetime(df_hist['effective_from'])
    df_hist = df_hist.sort_values(['emp_id', 'effective_from'])
    
    df_hist['valid_from'] = df_hist['effective_from']
    df_hist['next_effective_from'] = df_hist.groupby('emp_id')['effective_from'].shift(-1)
    df_hist['valid_to'] = df_hist['next_effective_from'] - pd.Timedelta(days=1)
    
    df_hist = df_hist.drop(columns=['next_effective_from', 'eff_from_dt', 'eff_to_dt'])
    df_hist['effective_from'] = df_hist['effective_from'].dt.strftime('%Y-%m-%d')
    df_hist['valid_from'] = df_hist['valid_from'].dt.strftime('%Y-%m-%d')
    df_hist['valid_to'] = df_hist['valid_to'].dt.strftime('%Y-%m-%d')
    df_hist['valid_to'] = df_hist['valid_to'].fillna('2099-12-31')
    
    conn.execute("DROP TABLE IF EXISTS staging.employment_history;")
    conn.execute("""
        CREATE TABLE staging.employment_history (
            emp_id TEXT,
            effective_from TEXT,
            effective_to TEXT,
            dept_id TEXT,
            job_title TEXT,
            salary TEXT,
            valid_from TEXT,
            valid_to TEXT
        );
    """)
    for _, row in df_hist.iterrows():
        conn.execute("""
            INSERT INTO staging.employment_history (emp_id, effective_from, effective_to, dept_id, job_title, salary, valid_from, valid_to)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(row.get('emp_id', '')).strip(), str(row.get('effective_from', '')).strip(), 
              str(row.get('effective_to', '')).strip(), str(row.get('dept_id', '')).strip(), 
              str(row.get('job_title', '')).strip(), str(row.get('salary', '')).strip(), 
              str(row.get('valid_from', '')).strip(), str(row.get('valid_to', '')).strip()))
    conn.commit()
    
    # ---------------------------------------------------------
    # 5. Process Shift Roster (Rule 6)
    # ---------------------------------------------------------
    print("Processing shift roster and filling missing weeks...")
    df_roster = pd.read_sql("SELECT * FROM raw.shift_roster", conn)
    df_roster = clean_col_names(df_roster)
    df_roster['week_start'] = pd.to_datetime(df_roster['week_start'])
    
    all_roster_rows = []
    for emp_id, group in df_roster.groupby('emp_id'):
        group = group.sort_values('week_start')
        min_week = group['week_start'].min()
        max_week = group['week_start'].max()
        
        full_weeks = pd.date_range(start=min_week, end=max_week, freq='W-MON')
        orig_shifts = group.set_index('week_start')['shift_code']
        
        for w in full_weeks:
            if w in orig_shifts:
                shift = orig_shifts[w]
                filled = 0
            else:
                valid_shifts = orig_shifts[orig_shifts.index <= w]
                shift = valid_shifts.iloc[-1] if not valid_shifts.empty else group['shift_code'].iloc[0]
                filled = 1
            all_roster_rows.append({
                'emp_id': emp_id,
                'week_start': w.strftime('%Y-%m-%d'),
                'shift_code': shift,
                'is_filled': filled
            })
            
    df_final_roster = pd.DataFrame(all_roster_rows)
    conn.execute("DROP TABLE IF EXISTS staging.shift_roster;")
    conn.execute("""
        CREATE TABLE staging.shift_roster (
            emp_id TEXT,
            week_start TEXT,
            shift_code TEXT,
            is_filled INTEGER
        );
    """)
    for r in all_roster_rows:
        conn.execute("""
            INSERT INTO staging.shift_roster (emp_id, week_start, shift_code, is_filled)
            VALUES (?, ?, ?, ?)
        """, (r['emp_id'], r['week_start'], r['shift_code'], r['is_filled']))
    conn.commit()
    
    # ---------------------------------------------------------
    # Verification & Results
    # ---------------------------------------------------------
    dept_count = conn.execute("SELECT COUNT(*) FROM staging.departments").fetchone()[0]
    shift_count = conn.execute("SELECT COUNT(*) FROM staging.shifts").fetchone()[0]
    hol_count = conn.execute("SELECT COUNT(*) FROM staging.holidays").fetchone()[0]
    hist_count = conn.execute("SELECT COUNT(*) FROM staging.employment_history").fetchone()[0]
    issues_count = conn.execute("SELECT COUNT(*) FROM staging.employment_history_issues").fetchone()[0]
    roster_count = conn.execute("SELECT COUNT(*) FROM staging.shift_roster").fetchone()[0]
    
    print("\n================ STAGE 2B RESULT ================")
    print(f"Departments loaded: {dept_count} (Expected: 25)")
    print(f"Shifts loaded: {shift_count} (Expected: 4)")
    print(f"Holidays loaded: {hol_count} (Expected: 12)")
    print(f"Employment History rows: {hist_count} (Expected: 3686)")
    print(f"Employment History Issues (Overlap/Gap): {issues_count} (Expected: ~37)")
    print(f"Shift Roster total rows: {roster_count}")
    
    if dept_count == 25 and shift_count == 4 and hol_count == 12 and hist_count == 3686:
        print("STATUS: PASS ✅")
    else:
        print("STATUS: RUK JAO 🛑 - Counts do not match expected values!")
        sys.exit(1)
        
    conn.close()

if __name__ == '__main__':
    run_stage_2b()