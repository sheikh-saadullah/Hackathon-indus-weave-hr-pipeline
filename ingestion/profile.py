"""
Stage 0: Data profiling.
Yeh script data/raw ki har file ko dekhti hai aur ek report banati hai.
Kuch badalti nahi, sirf parhti hai.
"""
import json
import re
from pathlib import Path

import pandas as pd

RAW_DIR = Path("data/raw")
REPORT_FILE = Path("profile_report.txt")

# PDF mein diye gaye rows ke numbers
EXPECTED_ROWS = {
    "employees.csv": 1316,
    "employment_history.csv": 3686,
    "departments.csv": 25,
    "shift_roster.csv": 36402,
    "device_mapping.csv": 1260,
    "biometric_punches.csv": 345280,
    "holidays.csv": 12,
    "overtime_requests.csv": 22098,
    "payroll_lines.csv": 53617,
    "applications.csv": 3835,
    "leave_requests.json": 5372,
    "shifts.json": 4,
}

lines = []  # report ki saari lines yahan jama hongi


def say(text=""):
    """Screen par bhi dikhao aur report ki list mein bhi rakho."""
    print(text)
    lines.append(text)


def date_format_of(value):
    """Ek date ka format pehchano."""
    value = value.strip()
    if value == "":
        return "BLANK"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "YYYY-MM-DD"
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
        return "DD/MM/YYYY"
    if re.fullmatch(r"\d{2}-[A-Za-z]{3}-\d{4}", value):
        return "DD-Mon-YYYY"
    return "OTHER"


def profile_csv(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    say("=" * 70)
    say(f"FILE: {path.name}")
    say("=" * 70)

    expected = EXPECTED_ROWS.get(path.name)
    status = "OK" if expected == len(df) else "MISMATCH"
    say(f"Rows: {len(df):,}   (PDF kehta hai: {expected:,})  -> {status}")
    say(f"Columns ({len(df.columns)}): {list(df.columns)}")
    say()

    say(f"{'column':28} {'blank':>8} {'unique':>9}")
    for col in df.columns:
        blanks = int((df[col].str.strip() == "").sum())
        uniques = df[col].nunique()
        say(f"{col:28} {blanks:>8,} {uniques:>9,}")
    say()

    # Jin columns mein kam alag values hain, unki ginti dikhao
    for col in df.columns:
        if df[col].nunique() <= 15:
            say(f"Values of '{col}':")
            counts = df[col].value_counts(dropna=False)
            for value, n in counts.items():
                say(f"    {value!r:30} {n:>8,}")
            say()

    # Duplicate IDs ka check (pehla column aksar ID hota hai)
    first_col = df.columns[0]
    dup_count = int(df[first_col].duplicated().sum())
    say(f"Duplicate values in first column '{first_col}': {dup_count:,}")
    say()
    return df


def profile_json(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    say("=" * 70)
    say(f"FILE: {path.name}")
    say("=" * 70)

    items = data
    if isinstance(data, dict):
        say(f"Top-level type: dict, keys = {list(data.keys())}")
        items = next((v for v in data.values() if isinstance(v, list)), [data])
    else:
        say("Top-level type: list")

    expected = EXPECTED_ROWS.get(path.name)
    status = "OK" if expected == len(items) else "MISMATCH"
    say(f"Records: {len(items):,}   (PDF kehta hai: {expected:,})  -> {status}")
    say("First record:")
    say(json.dumps(items[0], indent=2)[:1500])
    say()
    return items


def main():
    frames = {}
    for path in sorted(RAW_DIR.glob("*.csv")):
        frames[path.name] = profile_csv(path)
    for path in sorted(RAW_DIR.glob("*.json")):
        profile_json(path)

    # ---- employees.csv ke khaas checks ----
    emp = frames["employees.csv"]
    say("#" * 70)
    say("EXTRA CHECKS: employees.csv")
    say("#" * 70)
    for col in ["date_of_birth", "hire_date", "separation_date"]:
        formats = emp[col].map(date_format_of).value_counts()
        say(f"Date formats in '{col}':")
        for fmt, n in formats.items():
            say(f"    {fmt:14} {n:>6,}")
    say()
    say("Alag alag department spellings (stray spaces dikhane ke liye repr use hua):")
    for value, n in emp["department"].value_counts().items():
        say(f"    {value!r:35} {n:>6,}")
    say()
    dup_ids = emp[emp["emp_id"].duplicated(keep=False)].sort_values("emp_id")
    say(f"Employees jo 2+ baar aaye: {dup_ids['emp_id'].nunique()} ids, {len(dup_ids)} rows")
    say("Pehle 3 duplicate ids ka namoona:")
    say(dup_ids.head(6).to_string())
    say()

    # ---- punches ke khaas checks ----
    punches = frames["biometric_punches.csv"]
    say("#" * 70)
    say("EXTRA CHECKS: biometric_punches.csv")
    say("#" * 70)
    say("Punch per device:")
    for value, n in punches["device_id"].value_counts().items():
        say(f"    {value!r:20} {n:>8,}")
    say(f"Sample punch_time values: {punches['punch_time'].head(5).tolist()}")
    say(f"Min punch_time: {punches['punch_time'].min()}")
    say(f"Max punch_time: {punches['punch_time'].max()}")
    say()

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport save ho gayi: {REPORT_FILE}")


if __name__ == "__main__":
    main()