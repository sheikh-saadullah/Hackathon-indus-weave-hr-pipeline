"""
Stage 2A: raw.employees  ->  staging.employees (+ staging.employees_merge_log)

Kaam:
  1. Text saaf karo (extra spaces, casing)
  2. Teeno date formats ko YYYY-MM-DD banao
  3. Department ke naam departments.csv ki madad se standard karo
  4. Duplicate emp_id mein se latest updated_at wali row rakho, baaqi ka log likho
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.db import get_connection  # noqa: E402

# Wo columns jinki safai hoti hai (aur jinka duplicate rows mein farq dekha jata hai)
CLEAN_COLUMNS = [
    "full_name", "gender", "date_of_birth", "email", "phone", "plant", "department",
    "designation", "grade", "employment_type", "hire_date", "separation_date",
    "status", "annual_leave_entitlement",
]


# ---------------------------------------------------------------- chhote helpers
def clean_text(value):
    """Aage peeche ke spaces hatao aur beech ke multiple spaces ek karo."""
    return re.sub(r"\s+", " ", value).strip()


def parse_date(value):
    """Teeno formats ko YYYY-MM-DD banao. Khali ho to None."""
    value = clean_text(value)
    if value == "":
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):  # DD/MM/YYYY
        return datetime.strptime(value, "%d/%m/%Y").strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{2}-[A-Za-z]{3}-\d{4}", value):  # DD-Mon-YYYY
        return datetime.strptime(value, "%d-%b-%Y").strftime("%Y-%m-%d")
    raise ValueError(f"Ajeeb date format mila: {value!r}")


def clean_phone(value):
    """Sirf digits rakho, phir 0307-9559808 jaisa format do (agar 11 digits hon)."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11:
        return f"{digits[:4]}-{digits[4:]}"
    return digits  # ajeeb length ho to digits hi rehne do (neeche ginti print hogi)


def build_department_lookup(conn):
    """departments.csv se naam dhoondne ki tables banao."""
    rows = pd.read_sql_query(
        "SELECT dept_name, plant, previous_name FROM raw.departments", conn
    ).to_dict("records")

    current = {}      # (plant, naam) -> sahi naam
    old = {}          # (plant, purana naam) -> naya naam
    by_name = {}      # naam (kisi bhi plant ka) -> sahi naam
    old_by_name = {}  # purana naam (kisi bhi plant ka) -> naya naam
    for r in rows:
        plant = clean_text(r["plant"]).lower()
        name = clean_text(r["dept_name"])
        prev = clean_text(r["previous_name"])
        current[(plant, name.lower())] = name
        by_name[name.lower()] = name
        if prev:
            old[(plant, prev.lower())] = name
            old_by_name[prev.lower()] = name
    return current, old, by_name, old_by_name


def clean_department(plant, raw_department, lookup):
    """Wapas do: (sahi naam, purana naam tha? 1/0, mila? True/False)"""
    current, old, by_name, old_by_name = lookup
    key = clean_text(raw_department).lower()
    plant_key = clean_text(plant).lower()

    if (plant_key, key) in current:
        return current[(plant_key, key)], 0, True
    if (plant_key, key) in old:
        return old[(plant_key, key)], 1, True
    if key in by_name:
        return by_name[key], 0, True
    if key in old_by_name:
        return old_by_name[key], 1, True
    return clean_text(raw_department).title(), 0, False  # nahi mila: shak wali entry


def clean_row(r, lookup):
    """Ek raw row ko saaf karo."""
    department, was_renamed, found = clean_department(r["plant"], r["department"], lookup)
    return {
        "emp_id": clean_text(r["emp_id"]),
        "full_name": clean_text(r["full_name"]).title(),
        "gender": clean_text(r["gender"]).upper(),
        "date_of_birth": parse_date(r["date_of_birth"]),
        "email": clean_text(r["email"]).lower(),
        "phone": clean_phone(r["phone"]),
        "plant": clean_text(r["plant"]),
        "department": department,
        "department_was_renamed": was_renamed,
        "department_found": found,
        "designation": clean_text(r["designation"]),
        "grade": clean_text(r["grade"]).upper(),
        "employment_type": clean_text(r["employment_type"]),
        "hire_date": parse_date(r["hire_date"]),
        "separation_date": parse_date(r["separation_date"]),
        "status": clean_text(r["status"]),
        "annual_leave_entitlement": int(clean_text(r["annual_leave_entitlement"])),
        "updated_at": clean_text(r["updated_at"]),
        "raw_rowid": int(r["raw_rowid"]),
    }


# ---------------------------------------------------------------------- main
def main():
    conn = get_connection()

    raw_rows = pd.read_sql_query(
        "SELECT rowid AS raw_rowid, * FROM raw.employees", conn
    ).to_dict("records")
    raw_count = len(raw_rows)

    lookup = build_department_lookup(conn)
    cleaned = [clean_row(r, lookup) for r in raw_rows]

    # updated_at ka format check (taake text se sahi tarah compare ho sake)
    bad = [c["updated_at"] for c in cleaned
           if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", c["updated_at"])]
    if bad:
        print("updated_at ka format ajeeb hai, ruk jao:", bad[:5])
        sys.exit(1)

    # ---------- Duplicates: har emp_id mein se latest updated_at wali rakho ----------
    groups = {}
    for row in cleaned:
        groups.setdefault(row["emp_id"], []).append(row)

    kept, merge_log = [], []
    for emp_id, rows in groups.items():
        rows.sort(key=lambda x: (x["updated_at"], x["raw_rowid"]))  # sab se naya aakhir mein
        winner = rows[-1]
        kept.append(winner)
        for loser in rows[:-1]:
            diffs = [c for c in CLEAN_COLUMNS if loser[c] != winner[c]]
            if loser["updated_at"] == winner["updated_at"]:
                reason = "Same updated_at; file mein baad wali row rakhi"
            else:
                reason = (f"Duplicate emp_id; latest updated_at rakhi "
                          f"({winner['updated_at']} > {loser['updated_at']})")
            merge_log.append((
                emp_id, winner["raw_rowid"], loser["raw_rowid"],
                winner["updated_at"], loser["updated_at"], reason,
                ", ".join(diffs) if diffs else "safai ke baad bilkul same",
            ))

    # ---------- Staging tables banao (har baar naye sire se: idempotent) ----------
    conn.execute("DROP TABLE IF EXISTS staging.employees")
    conn.execute("DROP TABLE IF EXISTS staging.employees_merge_log")
    conn.execute(
        """
        CREATE TABLE staging.employees (
            emp_id                    TEXT PRIMARY KEY,
            full_name                 TEXT NOT NULL,
            gender                    TEXT,
            date_of_birth             TEXT,
            email                     TEXT,
            phone                     TEXT,
            plant                     TEXT NOT NULL,
            department                TEXT,
            department_was_renamed    INTEGER,
            designation               TEXT,
            grade                     TEXT,
            employment_type           TEXT,
            hire_date                 TEXT NOT NULL,
            separation_date           TEXT,
            status                    TEXT,
            annual_leave_entitlement  INTEGER,
            updated_at                TEXT,
            source_raw_rowid          INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE staging.employees_merge_log (
            emp_id               TEXT,
            kept_raw_rowid       INTEGER,
            dropped_raw_rowid    INTEGER,
            kept_updated_at      TEXT,
            dropped_updated_at   TEXT,
            reason               TEXT,
            columns_that_differed TEXT
        )
        """
    )

    conn.executemany(
        "INSERT INTO staging.employees VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["emp_id"], r["full_name"], r["gender"], r["date_of_birth"], r["email"],
          r["phone"], r["plant"], r["department"], r["department_was_renamed"],
          r["designation"], r["grade"], r["employment_type"], r["hire_date"],
          r["separation_date"], r["status"], r["annual_leave_entitlement"],
          r["updated_at"], r["raw_rowid"]) for r in kept],
    )
    conn.executemany("INSERT INTO staging.employees_merge_log VALUES (?,?,?,?,?,?,?)", merge_log)
    conn.commit()

    # ------------------------------ Verification ------------------------------
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    staging_count = q("SELECT COUNT(*) FROM staging.employees")
    merged_count = q("SELECT COUNT(*) FROM staging.employees_merge_log")

    print("\n===== STAGE 2A RESULT =====")
    print(f"raw.employees rows              : {raw_count:,}")
    print(f"staging.employees rows          : {staging_count:,}")
    print(f"merged away (merge_log) rows    : {merged_count:,}")
    ok = raw_count == staging_count + merged_count
    print(f"Reconcile raw = staging + merged: {'PASS' if ok else 'FAIL'}")

    not_iso = q("""SELECT COUNT(*) FROM staging.employees
                   WHERE date_of_birth NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                      OR hire_date     NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                      OR (separation_date IS NOT NULL AND separation_date
                          NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')""")
    print(f"Dates jo ISO nahi hain          : {not_iso}  (0 hona chahiye)")

    print(f"Alag department naam (ab)       : {q('SELECT COUNT(DISTINCT department) FROM staging.employees')}")
    print(f"Purane naam se naye mein badle  : {q('SELECT SUM(department_was_renamed) FROM staging.employees')}")
    unknown = sorted({r['department'] for r in kept if not r['department_found']})
    print(f"Department jo departments.csv mein nahi mile: {unknown if unknown else 'koi nahi'}")

    odd_phone = q("SELECT COUNT(*) FROM staging.employees WHERE LENGTH(REPLACE(phone,'-','')) <> 11")
    print(f"Phone jo 11 digits ke nahi      : {odd_phone}")

    mismatch = q("""SELECT COUNT(*) FROM staging.employees
                    WHERE (status = 'Separated' AND separation_date IS NULL)
                       OR (status = 'Active' AND separation_date IS NOT NULL)""")
    print(f"Status vs separation_date farq  : {mismatch}  (0 hona chahiye)")

    backwards = q("""SELECT COUNT(*) FROM staging.employees
                     WHERE separation_date IS NOT NULL AND separation_date < hire_date""")
    print(f"Separation hire se pehle        : {backwards}  (0 hona chahiye)")

    print("\nStatus ki ginti:")
    for status, n in conn.execute("SELECT status, COUNT(*) FROM staging.employees GROUP BY status"):
        print(f"    {status:10} {n:>6,}")

    print("\nDepartment (saaf shuda) ki list:")
    for dept, n in conn.execute(
        "SELECT department, COUNT(*) FROM staging.employees GROUP BY department ORDER BY department"
    ):
        print(f"    {dept:25} {n:>5}")


if __name__ == "__main__":
    main()