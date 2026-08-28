"""
DB helper for E2E test assertions the UI can't itself verify, plus test-only
setup steps for scenarios the UI has no field for. Not part of the app;
only used by the Playwright suite.

Usage:
  python db_helper.py get-by-employee-id <employee_id>
    Prints the row as JSON, or the literal string "null" if none exists.
    Used to prove "Deactivate" (is_active=false) and "Delete" (is_deleted=true)
    are both soft, non-destructive status changes - the row always still
    exists - and to verify saved field values server-side.

  python db_helper.py cleanup-fixtures
    Deletes any staff rows left over from a previous/interrupted test run,
    scoped strictly to first_name LIKE 'PWTestFixture%' - a name pattern no
    real employee record could ever match. Prints {"deleted": <count>}.

  python db_helper.py link-manager <staff_employee_id> <manager_employee_id>
    Sets staff.manager_id on <staff_employee_id> to <manager_employee_id>'s
    id. Add/Edit Staff Member has no Manager field in the UI, so this is
    the only way to set up the "staff member has subordinates" precondition
    NEG-006 needs - the assertion under test (deactivation blocked) still
    goes entirely through the real UI/route. Prints {"linked": true}.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv('.env')

import psycopg2
import psycopg2.extras

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cmd = sys.argv[1] if len(sys.argv) > 1 else None

if cmd == 'get-by-employee-id' and len(sys.argv) > 2:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, employee_id, first_name, last_name, phone, is_active, is_deleted, "
        "bank_account_number, ifsc_code, monthly_salary, manager_id "
        "FROM staff WHERE employee_id = %s",
        (sys.argv[2],),
    )
    row = cur.fetchone()
    print(json.dumps(dict(row), default=str) if row else 'null')
elif cmd == 'cleanup-fixtures':
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE first_name LIKE 'PWTestFixture%'")
    deleted = cur.rowcount
    conn.commit()
    print(json.dumps({'deleted': deleted}))
elif cmd == 'link-manager' and len(sys.argv) > 3:
    cur = conn.cursor()
    cur.execute("SELECT id FROM staff WHERE employee_id = %s", (sys.argv[3],))
    manager = cur.fetchone()
    if not manager:
        print(json.dumps({'error': f'manager {sys.argv[3]} not found'}), file=sys.stderr)
        sys.exit(1)
    cur.execute("UPDATE staff SET manager_id = %s WHERE employee_id = %s", (manager[0], sys.argv[2]))
    conn.commit()
    print(json.dumps({'linked': True}))
else:
    print(
        'Usage: python db_helper.py get-by-employee-id <employee_id> | cleanup-fixtures | '
        'link-manager <staff_employee_id> <manager_employee_id>',
        file=sys.stderr,
    )
    sys.exit(1)

conn.close()
