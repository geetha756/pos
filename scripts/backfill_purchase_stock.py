"""One-time migration: link pre-existing store_purchases rows that predate
the "purchases always allocate stock" change (routes/inventory.py,
_allocate_stock_ops) and give their stock to the matching location.

Before that change, a manual purchase (and an unlinked scanned-bill row)
only ever wrote a spend record to store_purchases — it never touched
location_inventory. This script finds every store_purchases row that still
has no master_inventory_id, finds-or-creates the matching catalog item
(case-insensitive name match, same rule the live app uses), adds its
quantity onto that location's stock, logs an inventory_transactions entry,
and stamps the purchase row with the resulting master_inventory_id so it
isn't picked up twice.

This is NOT part of the ongoing feature and is not run automatically on
startup — run it by hand, once, after deploying the change, on any
database carrying old unlinked purchase rows:

    .venv/bin/python scripts/backfill_purchase_stock.py [--dry-run]

Safe to re-run: once a row has a master_inventory_id it's skipped, so a
second run is a no-op.
"""
import argparse
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Report what would change without writing anything.')
    args = parser.parse_args()

    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print('DATABASE_URL is not set (expected in .env).', file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, location_id, item_name, quantity, unit, recorded_by
        FROM store_purchases
        WHERE master_inventory_id IS NULL
        ORDER BY purchased_at
    """)
    rows = cur.fetchall()

    if not rows:
        print('Nothing to backfill — every purchase row is already linked.')
        return

    print(f'{len(rows)} unlinked purchase row(s) found.')
    linked, created_items = 0, 0

    for row in rows:
        item_name = row['item_name'].strip()
        unit = row['unit'] or 'pieces'
        quantity = Decimal(str(row['quantity']))
        location_id = row['location_id']

        cur.execute("SELECT id FROM master_inventory WHERE lower(name) = lower(%s)", (item_name,))
        mi = cur.fetchone()
        if mi:
            mi_id = mi['id']
            cur.execute("UPDATE master_inventory SET unit = %s, is_active = TRUE WHERE id = %s", (unit, mi_id))
        else:
            cur.execute(
                "INSERT INTO master_inventory (name, category, unit, is_active) "
                "VALUES (%s, 'groceries', %s, TRUE) RETURNING id",
                (item_name, unit))
            mi_id = cur.fetchone()['id']
            created_items += 1

        cur.execute(
            "SELECT current_stock FROM location_inventory WHERE location_id = %s AND master_inventory_id = %s",
            (location_id, mi_id))
        inv = cur.fetchone()
        previous_stock = Decimal(str(inv['current_stock'])) if inv else Decimal('0')
        new_stock = previous_stock + quantity

        cur.execute("""
            INSERT INTO location_inventory (location_id, master_inventory_id, current_stock,
                                             last_restock_date, last_restock_quantity)
            VALUES (%s, %s, %s, CURRENT_DATE, %s)
            ON CONFLICT (location_id, master_inventory_id)
            DO UPDATE SET current_stock = location_inventory.current_stock + EXCLUDED.current_stock,
                          last_restock_date = CURRENT_DATE,
                          last_restock_quantity = EXCLUDED.last_restock_quantity,
                          last_updated = CURRENT_TIMESTAMP
        """, (location_id, mi_id, quantity, quantity))

        cur.execute("""
            INSERT INTO inventory_transactions
                (location_id, master_inventory_id, transaction_type, quantity,
                 previous_stock, new_stock, recorded_by, reference_id, reference_type, notes)
            VALUES (%s, %s, 'restock', %s, %s, %s, %s, %s, 'store_purchase', %s)
        """, (location_id, mi_id, quantity, previous_stock, new_stock,
              row['recorded_by'], row['id'], f'Backfilled purchase: {item_name}'))

        cur.execute("UPDATE store_purchases SET master_inventory_id = %s WHERE id = %s", (mi_id, row['id']))

        print(f'  {item_name}: +{quantity} {unit} -> stock {previous_stock} -> {new_stock}')
        linked += 1

    if args.dry_run:
        conn.rollback()
        print(f'\nDry run: would link {linked} purchase row(s), create {created_items} new catalog item(s). Nothing written.')
    else:
        conn.commit()
        print(f'\nDone: linked {linked} purchase row(s), created {created_items} new catalog item(s).')

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
