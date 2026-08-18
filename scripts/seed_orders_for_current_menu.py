"""One-time reset: wipe all existing orders/order_items (they're leftover
from the old menu, now orphaned — no master_menu_id link since that catalog
was cleared) and generate fresh sample orders against whatever menu items
actually exist in location_menu right now. Reads the current catalog live
from the DB — never hardcodes item names/prices — so it stays correct even
after you add the still-missing items (Puri x1, Sambar Idly x2/x3, Vada x4,
Water bottle, Idly x4) or edit any price.

Usage:
    .venv/bin/python scripts/seed_orders_for_current_menu.py [--days N] [--dry-run]
"""
import argparse
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, time as dtime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

random.seed(20260813)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=13, help='How many days of sample orders to generate (default 13)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # --- Wipe existing orders (all currently orphaned from the old menu) ---
        cur.execute("SELECT count(*) AS n FROM orders")
        old_order_count = cur.fetchone()['n']
        cur.execute("DELETE FROM order_items")
        cur.execute("DELETE FROM orders")

        # --- Read the live catalog: which items exist, at which location, what price/section ---
        cur.execute("""
            SELECT lm.id AS location_menu_id, lm.location_id, lm.master_menu_id,
                   mm.name, lm.price, COALESCE(lm.section, 'all') AS section
            FROM location_menu lm
            JOIN master_menu mm ON mm.id = lm.master_menu_id
            WHERE lm.is_available = TRUE AND mm.is_active = TRUE
        """)
        catalog = cur.fetchall()
        if not catalog:
            print('No menu items found in location_menu — nothing to generate orders against. '
                  'Add items to the menu first.')
            conn.rollback()
            return

        by_location = {}
        for row in catalog:
            by_location.setdefault(str(row['location_id']), []).append(row)

        # Combo pairs built from whatever's actually on the menu (beverage + food),
        # so "bought together"-style variety exists without hardcoding old item names.
        def build_pairs(items):
            bev = [r for r in items if r['name'] in ('Coffee', 'Tea')]
            food = [r for r in items if r not in bev]
            pairs = []
            for f in food:
                for b in bev:
                    if f['section'] in ('all', b['section']) or b['section'] == 'all':
                        pairs.append((f, b))
            return pairs or [(a, b) for a in items for b in items if a != b]

        hour_weights_all = {7: 2, 8: 5, 9: 6, 10: 4, 11: 3, 12: 7, 13: 8, 14: 4,
                             15: 3, 16: 4, 17: 5, 18: 7, 19: 9, 20: 6, 21: 2}
        morning_hours = list(range(6, 12))
        evening_hours = list(range(16, 22))

        today = date(2026, 8, 13)
        start_day = today - timedelta(days=args.days - 1)

        total_orders = 0
        for loc_id, items in by_location.items():
            pairs = build_pairs(items)
            singles = items

            for day_offset in range(args.days):
                d = start_day + timedelta(days=day_offset)
                is_weekend = d.weekday() >= 5
                n_orders = int(random.randint(16, 24) * (1.3 if is_weekend else 1.0))

                for _ in range(n_orders):
                    item_or_pair = random.choice(pairs) if random.random() < 0.55 else (random.choice(singles),)
                    # Bias hour choice toward a chosen item's own section when it has one.
                    chosen_names = [x['section'] for x in item_or_pair]
                    if 'morning' in chosen_names and 'evening' not in chosen_names:
                        hour = random.choice(morning_hours)
                    elif 'evening' in chosen_names and 'morning' not in chosen_names:
                        hour = random.choice(evening_hours)
                    else:
                        pool = []
                        for h, w in hour_weights_all.items():
                            pool += [h] * w
                        hour = random.choice(pool)
                    minute = random.randint(0, 59)
                    created_at_ist = datetime.combine(d, dtime(hour, minute))
                    created_at_utc = created_at_ist - timedelta(hours=5, minutes=30)

                    order_id = str(uuid.uuid4())
                    order_number = f"SNS{d.strftime('%Y%m%d')}{hour:02d}{minute:02d}{random.randint(100,999)}"
                    cancelled = random.random() < 0.04
                    payment_method = 'phonepe' if random.random() < 0.28 else 'cash'

                    items_payload = []
                    total = Decimal('0')
                    for row in item_or_pair:
                        qty = random.choice([1, 1, 1, 2])
                        price = Decimal(str(row['price']))
                        line_total = price * qty
                        total += line_total
                        items_payload.append((row, qty, price, line_total))
                    if random.random() < 0.12:
                        extra = random.choice(singles)
                        if extra not in [r for r, *_ in items_payload]:
                            qty = 1
                            price = Decimal(str(extra['price']))
                            items_payload.append((extra, qty, price, price))
                            total += price

                    if not args.dry_run:
                        cur.execute("""
                            INSERT INTO orders (id, location_id, order_number, order_type, status,
                                                 total_amount, payment_method, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (order_id, loc_id, order_number, random.choice(['dine-in', 'dine-in', 'takeaway']),
                              'cancelled' if cancelled else 'completed', total, payment_method,
                              created_at_utc, created_at_utc))
                        for row, qty, price, line_total in items_payload:
                            cur.execute("""
                                INSERT INTO order_items (id, order_id, location_menu_id, master_menu_id,
                                                          item_name, quantity, unit_price, total_price)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (str(uuid.uuid4()), order_id, row['location_menu_id'], row['master_menu_id'],
                                  row['name'], qty, price, line_total))
                    total_orders += 1

        if args.dry_run:
            conn.rollback()
            print(f'Dry run: would delete {old_order_count} old orders and insert {total_orders} new ones. Nothing written.')
        else:
            conn.commit()
            print(f'Deleted {old_order_count} old (orphaned) orders. '
                  f'Inserted {total_orders} new sample orders across {args.days} days, '
                  f'using {len(catalog)} current menu items.')
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
