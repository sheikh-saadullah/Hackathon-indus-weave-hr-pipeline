"""
Stage 1: Raw load.
data/raw ki har file ko raw schema mein jaisi hai waisi load karo:
  - sab columns TEXT
  - kuch flatten nahi (JSON ka har record ek text column mein)
  - 3 extra columns: _source_file, _loaded_at, _row_hash
  - dobara chalane par duplicate nahi banenge (idempotent)
"""
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

# Project ka root path python ko batao taake "common" mil jaye
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.db import get_connection  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"

# PDF mein diye gaye rows ke numbers
EXPECTED_ROWS = {
    "employees.csv": 1316,
    "employment_history.csv": 3686,
    "departments.csv": 25,
    "shifts.json": 4,
    "shift_roster.csv": 36402,
    "device_mapping.csv": 1260,
    "biometric_punches.csv": 345280,
    "holidays.csv": 12,
    "leave_requests.json": 5372,
    "overtime_requests.csv": 22098,
    "payroll_lines.csv": 53617,
    "applications.csv": 3835,
}


def make_row_hash(values):
    """Row ka 'fingerprint': same row ka hamesha same hash."""
    joined = "\x1f".join(values)  # \x1f = alag karne wala khaas nishan
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def read_csv_file(path):
    """CSV parho. Sab kuch text rehta hai, kuch badla nahi jata."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = []
        for line_no, row in enumerate(reader, start=2):
            if row == []:  # bilkul khali line chhor do
                continue
            if len(row) != len(header):
                raise ValueError(f"{path.name} line {line_no}: columns ka number galat hai")
            rows.append(row)
    return header, rows


def read_json_file(path):
    """JSON parho. Har record poora ek text column (raw_json) mein jata hai."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):  # shifts.json: {"shifts": [...]}
        data = next(v for v in data.values() if isinstance(v, list))
    rows = [[json.dumps(record, ensure_ascii=False)] for record in data]
    return ["raw_json"], rows


def create_load_log_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.load_log (
            run_at        TEXT,
            file_name     TEXT,
            table_name    TEXT,
            pdf_expected  INTEGER,
            rows_in_file  INTEGER,
            rows_in_table INTEGER,
            status        TEXT
        )
        """
    )


def load_one_file(conn, path, loaded_at):
    """Ek file ko raw table mein daalo aur row counts wapas do."""
    table = path.stem  # employees.csv -> employees

    if path.suffix == ".csv":
        header, rows = read_csv_file(path)
    else:
        header, rows = read_json_file(path)

    all_columns = header + ["_source_file", "_loaded_at", "_row_hash"]
    column_sql = ", ".join(f'"{c}" TEXT' for c in all_columns)
    conn.execute(f'CREATE TABLE IF NOT EXISTS raw."{table}" ({column_sql})')
    conn.commit()

    # Har row ke aage metadata jod do
    data = [tuple(r) + (path.name, loaded_at, make_row_hash(r)) for r in rows]
    placeholders = ", ".join("?" for _ in all_columns)
    column_names = ", ".join(f'"{c}"' for c in all_columns)

    try:
        # IDEMPOTENT TRICK: pehle is file ke purane rows hatao, phir naye daalo.
        # Dono kaam ek transaction mein hain: ya dono honge, ya kuch bhi nahi.
        conn.execute(f'DELETE FROM raw."{table}" WHERE _source_file = ?', (path.name,))
        conn.executemany(
            f'INSERT INTO raw."{table}" ({column_names}) VALUES ({placeholders})', data
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    rows_in_table = conn.execute(
        f'SELECT COUNT(*) FROM raw."{table}" WHERE _source_file = ?', (path.name,)
    ).fetchone()[0]

    return table, len(rows), rows_in_table


def main():
    conn = get_connection()
    create_load_log_table(conn)
    loaded_at = datetime.now().isoformat(timespec="seconds")

    files = sorted(RAW_DIR.glob("*.csv")) + sorted(RAW_DIR.glob("*.json"))
    results = []

    for path in files:
        print(f"Loading {path.name} ...")
        table, rows_in_file, rows_in_table = load_one_file(conn, path, loaded_at)
        expected = EXPECTED_ROWS.get(path.name)

        ok = rows_in_file == rows_in_table and (expected is None or rows_in_file == expected)
        status = "PASS" if ok else "FAIL"

        conn.execute(
            "INSERT INTO raw.load_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            (loaded_at, path.name, f"raw.{table}", expected, rows_in_file, rows_in_table, status),
        )
        conn.commit()
        results.append((path.name, f"raw.{table}", expected, rows_in_file, rows_in_table, status))

    # ---- Natija ki table ----
    print()
    print(f"{'File':26} {'Table':26} {'PDF':>8} {'File':>8} {'Table':>8}  Status")
    print("-" * 86)
    for name, table, expected, in_file, in_table, status in results:
        print(f"{name:26} {table:26} {expected:>8,} {in_file:>8,} {in_table:>8,}  {status}")

    failed = [r for r in results if r[5] == "FAIL"]
    print()
    if failed:
        print(f"{len(failed)} file(s) FAIL hui. Upar dekho.")
        sys.exit(1)
    print("Sab files PASS. Raw layer tayyar hai.")


if __name__ == "__main__":
    main()