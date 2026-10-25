# Issues log

## employees.csv
1. 50 duplicate emp_id (1,316 rows, 1,266 unique ids).
   Detected: COUNT(*) vs COUNT(DISTINCT emp_id) in profile.py.
   Fix: latest updated_at rakhi (transform/stage2a_employees.py).
   Log: staging.employees_merge_log (50 rows).
   Check: 1,316 = 1,266 staging + 50 merged. PASS.
2. Teen date formats (YYYY-MM-DD, DD/MM/YYYY, DD-Mon-YYYY) in date_of_birth,
   hire_date, separation_date.
   Fix: parse_date() sab ko YYYY-MM-DD. Non-ISO dates after fix: 0.
3. Department ke 81 spellings (casing, stray spaces, purane naam).
   Fix: clean_text + departments.csv lookup. Ab 19 naam.
   43 employees purane naam se naye naam mein map hue.
4. Phone ke mukhtalif formats (0307-9559808 vs 03079559808).
   Fix: sab 0XXX-XXXXXXX. 11 digits se alag: 0.
5. Naam ki casing (USMAN BALOCH vs Usman Baloch). Fix: Title Case.
6. Consistency: status vs separation_date farq 0; separation hire se pehle 0.