"""
Database helper.
Har script isi function se database kholegi, taake sab jagah ek jaisa setup ho.
"""
import sqlite3
from pathlib import Path

# Project ka sab se upar wala folder (jahan README aur data folder hai)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = PROJECT_ROOT / "db"

# Teen "almariyan": naam -> file
SCHEMAS = {
    "raw": DB_DIR / "raw.db",
    "staging": DB_DIR / "staging.db",
    "warehouse": DB_DIR / "warehouse.db",
}


def get_connection():
    """Teeno databases ko ek saath kholo aur unhein raw/staging/warehouse naam do."""
    DB_DIR.mkdir(exist_ok=True)

    # Main database memory mein hai (khali). Asli data teen attached files mein rahega.
    conn = sqlite3.connect(":memory:")

    for schema_name, file_path in SCHEMAS.items():
        conn.execute(f"ATTACH DATABASE ? AS {schema_name}", (str(file_path),))

    # Foreign keys (rishton ke rules) ON karo. Stage 4 mein kaam aayega.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn