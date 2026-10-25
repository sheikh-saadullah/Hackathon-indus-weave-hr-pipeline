"""
Database ko dekhne ka chhota tool.
Istemal:  python peek.py "SELECT * FROM raw.employees LIMIT 5"
"""
import sys

import pandas as pd

from common.db import get_connection

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 40)

if len(sys.argv) < 2:
    print('Aise chalao:  python peek.py "SELECT * FROM raw.employees LIMIT 5"')
    sys.exit(1)

conn = get_connection()
print(pd.read_sql_query(sys.argv[1], conn).to_string(index=False))