"""One-command rebuild of the Indus Weave HR pipeline."""
import subprocess, sys, os

STEPS = [
    "ingestion/load_raw.py",
    "transform/stage2a_employees.py",
    "transform/stage2b_reference_and_history.py",
    "transform/stage2c_biometric_punches.py",
    "transform/stage2d_leave_and_payroll.py",
    "transform/stage3_attendance_daily.py",
    "transform/stage4_warehouse_star_schema.py",
    "transform/stage5_business_questions_and_dq.py",
]

for step in STEPS:
    if not os.path.exists(step):
        print(f"SKIP (not found): {step}")
        continue
    print(f"\n>>> Running {step}")
    try:
        subprocess.check_call([sys.executable, step])
    except subprocess.CalledProcessError as e:
        print(f"FAILED: {step}")
        sys.exit(1)

print("\nPipeline complete.")
