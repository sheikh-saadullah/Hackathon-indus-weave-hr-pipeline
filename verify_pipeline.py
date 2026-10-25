import os
import sys
import pandas as pd

# Add project root to path so we can import common.db
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from common.db import get_connection

def verify_pipeline():
    conn = get_connection()
    print("==================================================")
    print("      INDUS WEAVE HR PIPELINE VERIFICATION        ")
    print("==================================================")
    
    tables = [
        "raw.employees", 
        "staging.employees", 
        "warehouse.dim_employee",
        "staging.departments", 
        "warehouse.dim_department",
        "staging.shifts", 
        "warehouse.dim_shift",
        "staging.attendance_daily", 
        "warehouse.fact_attendance",
        "warehouse.cfo_findings"
    ]
    
    all_passed = True
    
    for t in tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
            print(f"✅ {t:<30} : {cnt:,} rows")
        except Exception as e:
            print(f"❌ {t:<30} : Missing or Error")
            all_passed = False
            
    print("--------------------------------------------------")
    if all_passed:
        print("STATUS: ALL LAYERS VERIFIED SUCCESSFULLY! 🎉")
    else:
        print("STATUS: SOME TABLES HAVE ISSUES ⚠️")
    print("==================================================")
    
    conn.close()

if __name__ == '__main__':
    verify_pipeline()