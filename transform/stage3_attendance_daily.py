import sys
import os
import pandas as pd
import numpy as np

# Add project root to path so we can import common.db
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from common.db import get_connection

def run_stage_3():
    print("Starting Optimized Stage 3: Building staging.attendance_daily...")
    conn = get_connection()
    
    df_hist = pd.read_sql("SELECT emp_id, valid_from, valid_to, dept_id FROM staging.employment_history", conn)
    df_roster = pd.read_sql("SELECT emp_id, week_start, shift_code FROM staging.shift_roster", conn)
    df_shifts = pd.read_sql("SELECT shift_code, start_time, end_time, grace_minutes FROM staging.shifts", conn)
    df_holidays = pd.read_sql("SELECT holiday_date, plant FROM staging.holidays", conn)
    df_depts = pd.read_sql("SELECT dept_id, plant FROM staging.departments", conn)
    df_leave = pd.read_sql("SELECT emp_id, leave_date FROM staging.leave_days", conn)
    df_punches = pd.read_sql("SELECT emp_id, punch_time FROM staging.punches_clean", conn)
    conn.close()
    
    print("Vectorizing calendar and schedule generation...")
    df_hist['valid_from'] = pd.to_datetime(df_hist['valid_from'])
    df_hist['valid_to'] = pd.to_datetime(df_hist['valid_to'])
    
    all_dates = pd.date_range(start='2026-04-01', end='2026-09-30')
    
    rows = []
    for _, h in df_hist.iterrows():
        d_range = all_dates[(all_dates >= h['valid_from']) & (all_dates <= h['valid_to'])]
        if not d_range.empty:
            temp = pd.DataFrame({'emp_id': h['emp_id'], 'work_date': d_range, 'dept_id': h['dept_id']})
            rows.append(temp)
            
    df_sched = pd.concat(rows, ignore_index=True)
    df_sched['work_date_str'] = df_sched['work_date'].dt.strftime('%Y-%m-%d')
    df_sched['weekday'] = df_sched['work_date'].dt.day_of_week
    
    dept_plant = df_depts.set_index('dept_id')['plant'].to_dict()
    df_sched['plant'] = df_sched['dept_id'].map(dept_plant).fillna('Head Office')
    
    df_sched['monday'] = df_sched['work_date'] - pd.to_timedelta(df_sched['weekday'], unit='D')
    df_roster['week_start'] = pd.to_datetime(df_roster['week_start'])
    
    df_sched = df_sched.sort_values('work_date')
    df_roster = df_roster.sort_values('week_start')
    
    df_merged = pd.merge_asof(
        df_sched, 
        df_roster, 
        left_on='monday', 
        right_on='week_start', 
        by='emp_id', 
        direction='backward'
    )
    df_merged['shift_code'] = df_merged['shift_code'].fillna('GEN')
    
    df_punches['punch_dt'] = pd.to_datetime(df_punches['punch_time'])
    df_punches['work_date_str'] = df_punches['punch_dt'].dt.strftime('%Y-%m-%d')
    punch_agg = df_punches.groupby(['emp_id', 'work_date_str']).agg(
        check_in=('punch_dt', 'min'),
        check_out=('punch_dt', 'max'),
        punch_count=('punch_dt', 'count')
    ).reset_index()
    
    df_merged = pd.merge(df_merged, punch_agg, on=['emp_id', 'work_date_str'], how='left')
    
    holiday_set = set(zip(df_holidays['holiday_date'], df_holidays['plant']))
    holiday_all = set(df_holidays[df_holidays['plant'] == 'All']['holiday_date'])
    leave_set = set(zip(df_leave['emp_id'], df_leave['leave_date']))
    shift_dict = df_shifts.set_index('shift_code').to_dict('index')
    
    print("Calculating attendance status, late minutes and overtime...")
    statuses = []
    worked_hours = []
    late_mins = []
    early_mins = []
    overtime_hrs = []
    cin_list = []
    cout_list = []
    
    for _, row in df_merged.iterrows():
        d_str = row['work_date_str']
        wday = row['weekday']
        emp = row['emp_id']
        plt = row['plant']
        sc = row['shift_code']
        
        is_sunday = (wday == 6)
        is_hol = ((d_str, plt) in holiday_set) or (d_str in holiday_all)
        is_leave = ((emp, d_str) in leave_set)
        
        pc = row['punch_count']
        cin = row['check_in']
        cout = row['check_out']
        
        status = 'Absent'
        wh = 0.0
        lm = 0.0
        em = 0.0
        ot = 0.0
        cin_str = None
        cout_str = None
        
        if is_sunday:
            status = 'Weekly Off'
        elif is_hol:
            status = 'Holiday'
        elif is_leave:
            status = 'On Leave'
        elif pd.notna(pc) and pc >= 2:
            status = 'Present'
            cin_str = cin.strftime('%Y-%m-%d %H:%M:%S')
            cout_str = cout.strftime('%Y-%m-%d %H:%M:%S')
            
            wh = (cout - cin).total_seconds() / 3600.0
            s_info = shift_dict.get(sc, {'start_time': '09:00', 'end_time': '17:00', 'grace_minutes': 10})
            
            st_parts = str(s_info.get('start_time', '09:00')).split(':')
            et_parts = str(s_info.get('end_time', '17:00')).split(':')
            
            s_dt = cin.replace(hour=int(st_parts[0]), minute=int(st_parts[1]), second=0, microsecond=0)
            e_dt = cout.replace(hour=int(et_parts[0]), minute=int(et_parts[1]), second=0, microsecond=0)
            
            grace = float(s_info.get('grace_minutes', 10) or 10)
            diff_m = (cin - s_dt).total_seconds() / 60.0
            if diff_m > grace:
                lm = diff_m - grace
                
            ediff = (e_dt - cout).total_seconds() / 60.0
            if ediff > 10:
                em = ediff
                
            if cout > e_dt:
                ot_m = (cout - e_dt).total_seconds() / 60.0
                ot = (ot_m // 30) * 0.5
        elif pd.notna(pc) and pc == 1:
            status = 'Missing Punch'
            cin_str = cin.strftime('%Y-%m-%d %H:%M:%S')
            cout_str = cin_str
        else:
            status = 'Absent'
            
        statuses.append(status)
        worked_hours.append(round(wh, 2))
        late_mins.append(round(lm, 2))
        early_mins.append(round(em, 2))
        overtime_hrs.append(round(ot, 2))
        cin_list.append(cin_str)
        cout_list.append(cout_str)
        
    df_merged['status'] = statuses
    df_merged['worked_hours'] = worked_hours
    df_merged['late_minutes'] = late_mins
    df_merged['early_minutes'] = early_mins
    df_merged['overtime_hours'] = overtime_hrs
    df_merged['check_in'] = cin_list
    df_merged['check_out'] = cout_list
    
    final_df = df_merged[['emp_id', 'work_date_str', 'shift_code', 'status', 'check_in', 'check_out', 'worked_hours', 'late_minutes', 'early_minutes', 'overtime_hours']]
    final_df.columns = ['emp_id', 'work_date', 'shift_code', 'status', 'check_in', 'check_out', 'worked_hours', 'late_minutes', 'early_minutes', 'overtime_hours']
    
    print(f"Total attendance daily rows generated: {len(final_df)}")
    
    # Save using Temp Table Strategy for attached SQLite databases
    conn = get_connection()
    conn.execute("DROP TABLE IF EXISTS staging.attendance_daily;")
    conn.execute("""
        CREATE TABLE staging.attendance_daily (
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
    conn.commit()
    
    # Write dataframe to temp table first
    final_df.to_sql("attendance_daily_temp", conn, index=False, if_exists="replace", chunksize=10000)
    
    # Insert from temp table into staging schema table
    conn.execute("""
        INSERT INTO staging.attendance_daily 
        SELECT emp_id, work_date, shift_code, status, check_in, check_out, worked_hours, late_minutes, early_minutes, overtime_hours 
        FROM attendance_daily_temp;
    """)
    conn.execute("DROP TABLE attendance_daily_temp;")
    conn.commit()
    
    att_count = conn.execute("SELECT COUNT(*) FROM staging.attendance_daily").fetchone()[0]
    
    print(f"\n================ STAGE 3 RESULT ================")
    print(f"Staging Attendance Daily rows: {att_count}")
    
    if att_count > 0:
        print("STATUS: PASS ✅")
    else:
        print("STATUS: RUK JAO 🛑 - Table is empty!")
        sys.exit(1)
        
    conn.close()

if __name__ == '__main__':
    run_stage_3()