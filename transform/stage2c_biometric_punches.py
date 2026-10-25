import sys
import os
import pandas as pd
import re

# Add project root to path so we can import common.db
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from common.db import get_connection

def clean_col_names(df):
    """Helper to clean column names so they are SQL-safe."""
    df.columns = [re.sub(r'[^a-zA-Z0-9_]', '_', str(c)).strip('_') for c in df.columns]
    return df

def run_stage_2c():
    print("Starting Stage 2C: Biometric Punches, Clock Drift & Deduplication...")
    conn = get_connection()
    
    # ---------------------------------------------------------
    # 1. Load Device Mapping
    # ---------------------------------------------------------
    print("Processing device mapping...")
    df_map = pd.read_sql("SELECT * FROM raw.device_mapping", conn)
    df_map = clean_col_names(df_map)
    for col in df_map.select_dtypes(include=['object']).columns:
        df_map[col] = df_map[col].astype(str).str.strip()
        
    conn.execute("DROP TABLE IF EXISTS staging.device_mapping;")
    conn.execute("""
        CREATE TABLE staging.device_mapping (
            device_id TEXT,
            device_user_id TEXT,
            emp_id TEXT
        );
    """)
    for _, row in df_map.iterrows():
        conn.execute("INSERT INTO staging.device_mapping (device_id, device_user_id, emp_id) VALUES (?, ?, ?)",
                     (row.get('device_id'), row.get('device_user_id'), row.get('emp_id')))
    conn.commit()
    
    # ---------------------------------------------------------
    # 2. Load Raw Biometric Punches
    # ---------------------------------------------------------
    print("Processing raw biometric punches...")
    df_punches = pd.read_sql("SELECT * FROM raw.biometric_punches", conn)
    df_punches = clean_col_names(df_punches)
    for col in df_punches.select_dtypes(include=['object']).columns:
        df_punches[col] = df_punches[col].astype(str).str.strip()
        
    raw_punch_count = len(df_punches)
    print(f"Total raw punches loaded: {raw_punch_count}")
    
    # ---------------------------------------------------------
    # 3. Clock Drift Detection & Correction (Rule 11)
    # ---------------------------------------------------------
    print("Detecting and correcting clock drift across devices...")
    # Convert punch_time to datetime
    df_punches['punch_time_dt'] = pd.to_datetime(df_punches['punch_time'])
    df_punches['time_only'] = df_punches['punch_time_dt'].dt.time
    
    # Let's inspect average check-in times per device to find the drift (~1 hour off)
    # Hint from case study: Compare average check-in time per device vs shift start.
    # Let's calculate average hour of punches per device for morning hours (e.g. 05:00 to 09:00)
    morning_punches = df_punches[(df_punches['punch_time_dt'].dt.hour >= 5) & (df_punches['punch_time_dt'].dt.hour <= 9)]
    device_avg_hours = morning_punches.groupby('device_id')['punch_time_dt'].apply(lambda x: x.dt.hour.mean())
    print("Device average morning punch hours:")
    print(device_avg_hours)
    
    # Identify drift device (typically one device is ~1 hour ahead or behind, e.g. DEV-KOR-01 or DEV-HO-01)
    # Let's adjust based on standard finding in Indus Weave dataset where one device drifts by -1 hour (or +1 hour)
    # Let's check which device has an offset. Usually, if normal avg is ~06:30 and one device is ~07:30, it's +1 hour off so we subtract 1 hour.
    # Let's compute shift start comparison or automatically shift the outlier device.
    # Let's check exact offsets per device:
    drift_device = None
    drift_hours = 0
    
    # Automated drift detection: find device whose average time deviates most from median device average
    global_median_hour = device_avg_hours.median()
    for dev, avg_h in device_avg_hours.items():
        diff = avg_h - global_median_hour
        if abs(diff) > 0.5: # More than 30 mins deviation
            drift_device = dev
            drift_hours = round(diff)
            print(f"Found clock drift on device {dev}: average hour deviation is {diff:.2f} hours. Adjusting by {-drift_hours} hours.")
            
    if drift_device:
        # Correct the clock drift
        mask = df_punches['device_id'] == drift_device
        df_punches.loc[mask, 'punch_time_dt'] = df_punches.loc[mask, 'punch_time_dt'] - pd.Timedelta(hours=drift_hours)
        df_punches['punch_time'] = df_punches['punch_time_dt'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
    # ---------------------------------------------------------
    # 4. Map Punches & Reject Unmapped (Rule 8)
    # ---------------------------------------------------------
    print("Mapping punches to employee IDs and separating unmapped...")
    # Merge with device_mapping on device_id AND device_user_id (BOTH)
    mapping_df = pd.read_sql("SELECT device_id, device_user_id, emp_id FROM staging.device_mapping", conn)
    
    merged = pd.merge(df_punches, mapping_df, on=['device_id', 'device_user_id'], how='left')
    
    # Unmapped -> staging.rejected_punches
    rejected_mask = merged['emp_id'].isna() | (merged['emp_id'] == '') | (merged['emp_id'] == 'nan')
    df_rejected = merged[rejected_mask].copy()
    df_rejected['rejection_reason'] = 'Unmapped device_user_id'
    
    df_accepted = merged[~rejected_mask].copy()
    
    conn.execute("DROP TABLE IF EXISTS staging.rejected_punches;")
    conn.execute("""
        CREATE TABLE staging.rejected_punches (
            punch_id TEXT,
            device_id TEXT,
            device_user_id TEXT,
            punch_time TEXT,
            rejection_reason TEXT
        );
    """)
    for _, row in df_rejected.iterrows():
        conn.execute("INSERT INTO staging.rejected_punches (punch_id, device_id, device_user_id, punch_time, rejection_reason) VALUES (?, ?, ?, ?, ?)",
                     (str(row.get('punch_id')), str(row.get('device_id')), str(row.get('device_user_id')), str(row.get('punch_time')), row.get('rejection_reason')))
    conn.commit()
    
    # ---------------------------------------------------------
    # 5. 2-Minute Deduplication using LAG() (Rule 9)
    # ---------------------------------------------------------
    print("Applying 2-minute deduplication using LAG()...")
    df_accepted = df_accepted.sort_values(['emp_id', 'punch_time_dt'])
    
    # Calculate time difference with previous punch for the same employee
    df_accepted['prev_punch_time'] = df_accepted.groupby('emp_id')['punch_time_dt'].shift(1)
    df_accepted['time_diff_seconds'] = (df_accepted['punch_time_dt'] - df_accepted['prev_punch_time']).dt.total_seconds()
    
    # Rule 9: Two punches by the same employee within 2 minutes (= 120 seconds) count as one (keep first, drop subsequent)
    duplicate_mask = (df_accepted['time_diff_seconds'].notna()) & (df_accepted['time_diff_seconds'] <= 120)
    
    df_duplicates = df_accepted[duplicate_mask].copy()
    df_clean = df_accepted[~duplicate_mask].copy()
    
    print(f"Total raw: {raw_punch_count}")
    print(f"Rejected (unmapped): {len(df_rejected)}")
    print(f"Duplicates removed (within 2 min): {len(df_duplicates)}")
    print(f"Clean punches kept: {len(df_clean)}")
    
    # Save clean punches to staging.punches_clean
    conn.execute("DROP TABLE IF EXISTS staging.punches_clean;")
    conn.execute("""
        CREATE TABLE staging.punches_clean (
            punch_id TEXT,
            device_id TEXT,
            device_user_id TEXT,
            emp_id TEXT,
            punch_time TEXT
        );
    """)
    for _, row in df_clean.iterrows():
        conn.execute("INSERT INTO staging.punches_clean (punch_id, device_id, device_user_id, emp_id, punch_time) VALUES (?, ?, ?, ?, ?)",
                     (str(row.get('punch_id')), str(row.get('device_id')), str(row.get('device_user_id')), str(row.get('emp_id')), str(row.get('punch_time'))))
    conn.commit()
    
    # ---------------------------------------------------------
    # Verification & Results
    # ---------------------------------------------------------
    clean_count = conn.execute("SELECT COUNT(*) FROM staging.punches_clean").fetchone()[0]
    rejected_count = conn.execute("SELECT COUNT(*) FROM staging.rejected_punches").fetchone()[0]
    
    print("\n================ STAGE 2C RESULT ================")
    print(f"Raw Punches: {raw_punch_count}")
    print(f"Clean Punches Kept: {clean_count}")
    print(f"Rejected Punches (Unmapped): {rejected_count}")
    print(f"Duplicates Removed: {len(df_duplicates)}")
    print(f"Reconciliation Check (Raw == Clean + Rejected + Duplicates): {raw_punch_count} == {clean_count + rejected_count + len(df_duplicates)}")
    
    if raw_punch_count == (clean_count + rejected_count + len(df_duplicates)):
        print("STATUS: PASS ✅")
    else:
        print("STATUS: RUK JAO 🛑 - Reconciliation mismatch!")
        sys.exit(1)
        
    conn.close()

if __name__ == '__main__':
    run_stage_2c()