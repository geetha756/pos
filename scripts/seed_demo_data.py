"""Seed realistic demo data across the app's operational tables, so every
page built this session (Orders, Purchases, Groceries, Location Inventory,
Recipes, and all 8 Analytics pages) has something real to show instead of
an empty state.

Scope (deliberately, not "literally every table" — payroll/leave/holidays/
breaks/machines/purchase_lists are separate modules untouched this session):
  locations, departments, positions, staff, suppliers, master_inventory,
  location_inventory, master_menu, location_menu, recipe_items,
  orders + order_items (13 days, both locations, realistic hourly/weekend
  shape), daily_inventory_usage, store_purchases.

Safe to re-run: every entity table is looked up by its unique column first
(get-or-create), and orders use deterministic order numbers, so running
this twice does not duplicate data.

Usage:
    .venv/bin/python scripts/seed_demo_data.py [--dry-run]
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

random.seed(20260812)  # deterministic — reruns produce the same numbers


def get_or_create(cur, table, unique_col, unique_val, insert_cols, insert_vals):
    cur.execute(f"SELECT id FROM {table} WHERE {unique_col} = %s", (unique_val,))
    row = cur.fetchone()
    if row:
        return row['id']
    cols_sql = ', '.join(insert_cols)
    ph = ', '.join(['%s'] * len(insert_vals))
    cur.execute(f"INSERT INTO {table} ({cols_sql}) VALUES ({ph}) RETURNING id", insert_vals)
    return cur.fetchone()['id']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    database_url = os.getenv('DATABASE_URL')
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # ---------------------------------------------------------------
        # Locations
        # ---------------------------------------------------------------
        loc_amaravathi = get_or_create(cur, 'locations', 'name', 'Amaravathi',
            ['name', 'address', 'city', 'state', 'phone'],
            ['Amaravathi', 'Main Road, Near Bus Stand', 'Amaravathi', 'Andhra Pradesh', '9876543210'])
        loc_vijayawada = get_or_create(cur, 'locations', 'name', 'Vijayawada',
            ['name', 'address', 'city', 'state', 'phone'],
            ['Vijayawada', 'MG Road', 'Vijayawada', 'Andhra Pradesh', '9876543211'])
        locations = [loc_amaravathi, loc_vijayawada]

        # ---------------------------------------------------------------
        # Departments & positions
        # ---------------------------------------------------------------
        dept_kitchen = get_or_create(cur, 'departments', 'name', 'Kitchen',
            ['name', 'description'], ['Kitchen', 'Food & beverage preparation'])
        dept_counter = get_or_create(cur, 'departments', 'name', 'Counter',
            ['name', 'description'], ['Counter', 'Order taking & billing'])
        dept_mgmt = get_or_create(cur, 'departments', 'name', 'Management',
            ['name', 'description'], ['Management', 'Store & business operations'])

        pos_cook = get_or_create(cur, 'positions', 'title', 'Cook',
            ['title', 'department_id'], ['Cook', dept_kitchen])
        pos_cashier = get_or_create(cur, 'positions', 'title', 'Cashier',
            ['title', 'department_id'], ['Cashier', dept_counter])
        pos_manager = get_or_create(cur, 'positions', 'title', 'Store Manager',
            ['title', 'department_id'], ['Store Manager', dept_mgmt])

        # ---------------------------------------------------------------
        # Staff (one per role per location, roughly)
        # ---------------------------------------------------------------
        staff_defs = [
            ('SNS-001', 'Ravi', 'Kumar', pos_cook, dept_kitchen, loc_amaravathi),
            ('SNS-002', 'Lakshmi', 'Devi', pos_cashier, dept_counter, loc_amaravathi),
            ('SNS-003', 'Suresh', 'Babu', pos_manager, dept_mgmt, loc_amaravathi),
            ('SNS-004', 'Anitha', 'Reddy', pos_cook, dept_kitchen, loc_vijayawada),
            ('SNS-005', 'Prasad', 'Rao', pos_cashier, dept_counter, loc_vijayawada),
        ]
        staff_ids = []
        for emp_id, fn, ln, pos_id, dep_id, loc_id in staff_defs:
            sid = get_or_create(cur, 'staff', 'employee_id', emp_id,
                ['employee_id', 'first_name', 'last_name', 'position_id', 'department_id',
                 'location_id', 'hire_date'],
                [emp_id, fn, ln, pos_id, dep_id, loc_id, date(2025, 6, 1)])
            staff_ids.append(sid)
        recorder_staff = staff_ids[0]  # used as recorded_by for usage/purchase rows

        # ---------------------------------------------------------------
        # Suppliers
        # ---------------------------------------------------------------
        sup_dairy = get_or_create(cur, 'suppliers', 'name', 'Fresh Dairy Co.',
            ['name', 'contact_person', 'phone', 'payment_terms'],
            ['Fresh Dairy Co.', 'Venkat', '9812345670', 'Net 7'])
        sup_provisions = get_or_create(cur, 'suppliers', 'name', 'Sri Lakshmi Provisions',
            ['name', 'contact_person', 'phone', 'payment_terms'],
            ['Sri Lakshmi Provisions', 'Ramesh', '9812345671', 'Net 15'])

        # ---------------------------------------------------------------
        # Master inventory (ingredients)
        # ---------------------------------------------------------------
        ingredient_defs = [
            ('Milk', 'groceries', 'liter', sup_dairy),
            ('Tea Powder', 'groceries', 'kg', sup_provisions),
            ('Coffee Powder', 'groceries', 'kg', sup_provisions),
            ('Sugar', 'groceries', 'kg', sup_provisions),
            ('Bread', 'groceries', 'pieces', sup_provisions),
            ('Butter', 'groceries', 'kg', sup_dairy),
            ('Rava (Semolina)', 'groceries', 'kg', sup_provisions),
            ('Urad Dal', 'groceries', 'kg', sup_provisions),
            ('Potato', 'groceries', 'kg', sup_provisions),
            ('Cooking Oil', 'groceries', 'liter', sup_provisions),
            ('Lemon', 'groceries', 'pieces', sup_provisions),
        ]
        ingredients = {}
        for name, cat, unit, sup in ingredient_defs:
            iid = get_or_create(cur, 'master_inventory', 'name', name,
                ['name', 'category', 'unit', 'supplier_id'], [name, cat, unit, sup])
            ingredients[name] = iid

        # ---------------------------------------------------------------
        # Location inventory — current stock + minimum threshold per store.
        # Milk and Tea Powder deliberately low at Amaravathi to demonstrate
        # Low/Out-of-Stock badges and Stock Runway urgency.
        # ---------------------------------------------------------------
        stock_defs = {
            loc_amaravathi: {
                'Milk': (1.5, 3.0), 'Tea Powder': (0.4, 1.0), 'Coffee Powder': (1.2, 1.0),
                'Sugar': (8.0, 2.0), 'Bread': (20, 10), 'Butter': (2.0, 1.0),
                'Rava (Semolina)': (6.0, 3.0), 'Urad Dal': (4.0, 2.0),
                'Potato': (10.0, 4.0), 'Cooking Oil': (5.0, 2.0), 'Lemon': (30, 15),
            },
            loc_vijayawada: {
                'Milk': (6.0, 3.0), 'Tea Powder': (2.0, 1.0), 'Coffee Powder': (2.5, 1.0),
                'Sugar': (14.0, 2.0), 'Bread': (35, 10), 'Butter': (3.5, 1.0),
                'Rava (Semolina)': (9.0, 3.0), 'Urad Dal': (7.0, 2.0),
                'Potato': (18.0, 4.0), 'Cooking Oil': (9.0, 2.0), 'Lemon': (60, 15),
            },
        }
        for loc_id, items in stock_defs.items():
            for name, (stock, min_level) in items.items():
                cur.execute("""
                    INSERT INTO location_inventory (location_id, master_inventory_id, current_stock, minimum_stock_level)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (location_id, master_inventory_id) DO UPDATE SET
                        current_stock = EXCLUDED.current_stock, minimum_stock_level = EXCLUDED.minimum_stock_level
                """, (loc_id, ingredients[name], stock, min_level))

        # ---------------------------------------------------------------
        # Master menu (across 3 categories) + location menu (both stores)
        # ---------------------------------------------------------------
        menu_defs = [
            ('Masala Chai', 'Beverages', 20),
            ('Filter Coffee', 'Beverages', 25),
            ('Lemon Juice', 'Beverages', 20),
            ('Samosa', 'Snacks', 20),
            ('Bonda', 'Snacks', 15),
            ('Bread Omelette', 'Snacks', 40),
            ('Idly', 'Tiffins', 30),
            ('Vada', 'Tiffins', 25),
            ('Dosa', 'Tiffins', 40),
        ]
        menu_ids = {}
        location_menu_ids = {}  # (loc, menu_name) -> location_menu.id
        for name, category, price in menu_defs:
            mid = get_or_create(cur, 'master_menu', 'name', name,
                ['name', 'category', 'is_active'], [name, category, True])
            menu_ids[name] = mid
            for loc_id in locations:
                cur.execute("""
                    INSERT INTO location_menu (location_id, master_menu_id, price, is_available)
                    VALUES (%s, %s, %s, TRUE)
                    ON CONFLICT (location_id, master_menu_id) DO UPDATE SET price = EXCLUDED.price
                    RETURNING id
                """, (loc_id, mid, price))
                location_menu_ids[(loc_id, name)] = cur.fetchone()['id']

        # ---------------------------------------------------------------
        # Recipes — bill of materials per menu item
        # ---------------------------------------------------------------
        recipe_defs = {
            'Masala Chai': [('Milk', 0.05), ('Tea Powder', 0.01), ('Sugar', 0.015)],
            'Filter Coffee': [('Milk', 0.06), ('Coffee Powder', 0.015), ('Sugar', 0.01)],
            'Lemon Juice': [('Lemon', 1), ('Sugar', 0.02)],
            'Samosa': [('Potato', 0.08), ('Cooking Oil', 0.02)],
            'Bonda': [('Urad Dal', 0.03), ('Cooking Oil', 0.02)],
            'Bread Omelette': [('Bread', 2), ('Butter', 0.01)],
            'Idly': [('Rava (Semolina)', 0.08), ('Urad Dal', 0.02)],
            'Vada': [('Urad Dal', 0.05), ('Cooking Oil', 0.03)],
            'Dosa': [('Rava (Semolina)', 0.07), ('Cooking Oil', 0.015)],
        }
        for menu_name, items in recipe_defs.items():
            for ing_name, qty in items:
                cur.execute("""
                    INSERT INTO recipe_items (master_menu_id, master_inventory_id, quantity_per_unit)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (master_menu_id, master_inventory_id)
                    DO UPDATE SET quantity_per_unit = EXCLUDED.quantity_per_unit
                """, (menu_ids[menu_name], ingredients[ing_name], qty))

        # ---------------------------------------------------------------
        # Orders + order_items — 13 days, both locations, realistic shape:
        # morning/lunch/evening bumps, heavier weekends, a few cancellations,
        # cash/phonepe mix, item pairs that co-occur (feeds Bought Together).
        # ---------------------------------------------------------------
        combo_pairs = [
            ['Masala Chai', 'Samosa'], ['Filter Coffee', 'Bonda'],
            ['Idly', 'Vada'], ['Masala Chai', 'Bread Omelette'], ['Dosa', 'Filter Coffee'],
        ]
        singles = list(menu_defs)
        today = date(2026, 8, 11)  # matches the live app's IST "today" this session
        start_day = today - timedelta(days=12)

        # hour -> relative weight (closed before 7, after 21; lunch + evening peaks)
        hour_weights = {7: 2, 8: 5, 9: 6, 10: 4, 11: 3, 12: 7, 13: 8, 14: 4,
                         15: 3, 16: 4, 17: 5, 18: 7, 19: 9, 20: 6, 21: 2}
        hours_pool = []
        for h, w in hour_weights.items():
            hours_pool += [h] * w

        order_seq = 1
        order_ops = 0
        for day_offset in range(13):
            d = start_day + timedelta(days=day_offset)
            is_weekend = d.weekday() >= 5  # Sat/Sun
            for loc_id in locations:
                base_count = 16 if loc_id == loc_amaravathi else 22
                n_orders = int(base_count * (1.35 if is_weekend else 1.0))
                for _ in range(n_orders):
                    hour = random.choice(hours_pool)
                    minute = random.randint(0, 59)
                    created_at_ist = datetime.combine(d, dtime(hour, minute))
                    created_at_utc = created_at_ist - timedelta(hours=5, minutes=30)

                    order_id = str(uuid.uuid4())
                    order_number = f"SEED{d.strftime('%Y%m%d')}{loc_id.hex[:4] if hasattr(loc_id,'hex') else str(loc_id)[:4]}{order_seq:04d}"
                    order_seq += 1

                    cur.execute("SELECT 1 FROM orders WHERE order_number = %s", (order_number,))
                    if cur.fetchone():
                        continue  # already seeded (rerun)

                    cancelled = random.random() < 0.04
                    payment_method = 'phonepe' if random.random() < 0.28 else 'cash'

                    # Build the item list: a combo pair most of the time, a single item sometimes.
                    if random.random() < 0.55:
                        chosen_names = random.choice(combo_pairs)
                    else:
                        chosen_names = [random.choice(singles)[0]]
                    if random.random() < 0.15 and len(chosen_names) < 3:
                        extra = random.choice(singles)[0]
                        if extra not in chosen_names:
                            chosen_names.append(extra)

                    items_payload = []
                    total = Decimal('0')
                    for name in chosen_names:
                        price = Decimal(str(next(p for n, c, p in menu_defs if n == name)))
                        qty = random.choice([1, 1, 1, 2])
                        line_total = price * qty
                        total += line_total
                        items_payload.append((name, qty, price, line_total, location_menu_ids[(loc_id, name)], menu_ids[name]))

                    cur.execute("""
                        INSERT INTO orders (id, location_id, order_number, order_type, status,
                                             total_amount, payment_method, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (order_id, loc_id, order_number, random.choice(['dine-in', 'dine-in', 'takeaway']),
                          'cancelled' if cancelled else 'completed', total, payment_method,
                          created_at_utc, created_at_utc))

                    for name, qty, price, line_total, lm_id, mm_id in items_payload:
                        cur.execute("""
                            INSERT INTO order_items (id, order_id, location_menu_id, master_menu_id,
                                                      item_name, quantity, unit_price, total_price)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (str(uuid.uuid4()), order_id, lm_id, mm_id, name, qty, price, line_total))

                    order_ops += 1

        # ---------------------------------------------------------------
        # Daily inventory usage — manual usage logs per day/location/ingredient,
        # feeding Inventory Trend + Stock Runway (independent of recipe deduction,
        # exactly like the real "Daily Usage" feature).
        # ---------------------------------------------------------------
        usage_rate = {  # (typical units/day at the busier store; Amaravathi scaled down)
            'Milk': 1.6, 'Tea Powder': 0.35, 'Coffee Powder': 0.25, 'Sugar': 0.5,
            'Bread': 6, 'Butter': 0.15, 'Rava (Semolina)': 0.9, 'Urad Dal': 0.6,
            'Potato': 1.1, 'Cooking Oil': 0.6, 'Lemon': 8,
        }
        usage_ops = 0
        for day_offset in range(13):
            d = start_day + timedelta(days=day_offset)
            for loc_id in locations:
                scale = 1.0 if loc_id == loc_vijayawada else 0.65
                for name, rate in usage_rate.items():
                    used = round(rate * scale * random.uniform(0.75, 1.25), 3)
                    opening = round(used * random.uniform(3, 6), 2)
                    closing = round(max(opening - used, 0), 2)
                    cur.execute("""
                        INSERT INTO daily_inventory_usage
                            (location_id, master_inventory_id, date, opening_stock, closing_stock,
                             used_quantity, recorded_by, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'recorded')
                        ON CONFLICT (location_id, master_inventory_id, date) DO NOTHING
                    """, (loc_id, ingredients[name], d, opening, closing, used, recorder_staff))
                    usage_ops += 1

        # ---------------------------------------------------------------
        # Store purchases — a handful of spend/restock log entries.
        # ---------------------------------------------------------------
        # One purchase per ingredient per store, so every recipe ingredient has
        # a recent price to cost from — this is what feeds Menu Profitability.
        purchase_defs = [
            (loc_vijayawada, 'Milk', 20, 'liter', Decimal('1100.00'), start_day + timedelta(days=1)),
            (loc_vijayawada, 'Tea Powder', 5, 'kg', Decimal('1250.00'), start_day + timedelta(days=3)),
            (loc_amaravathi, 'Bread', 40, 'pieces', Decimal('1600.00'), start_day + timedelta(days=4)),
            (loc_amaravathi, 'Sugar', 15, 'kg', Decimal('720.00'), start_day + timedelta(days=6)),
            (loc_vijayawada, 'Cooking Oil', 15, 'liter', Decimal('2250.00'), start_day + timedelta(days=8)),
            (loc_amaravathi, 'Milk', 10, 'liter', Decimal('580.00'), start_day + timedelta(days=2)),
            (loc_amaravathi, 'Tea Powder', 2, 'kg', Decimal('520.00'), start_day + timedelta(days=5)),
            (loc_vijayawada, 'Sugar', 20, 'kg', Decimal('940.00'), start_day + timedelta(days=7)),
            (loc_vijayawada, 'Coffee Powder', 4, 'kg', Decimal('2600.00'), start_day + timedelta(days=2)),
            (loc_amaravathi, 'Coffee Powder', 2, 'kg', Decimal('1340.00'), start_day + timedelta(days=9)),
            (loc_vijayawada, 'Lemon', 100, 'pieces', Decimal('600.00'), start_day + timedelta(days=1)),
            (loc_amaravathi, 'Lemon', 50, 'pieces', Decimal('320.00'), start_day + timedelta(days=6)),
            (loc_vijayawada, 'Potato', 25, 'kg', Decimal('875.00'), start_day + timedelta(days=3)),
            (loc_amaravathi, 'Potato', 15, 'kg', Decimal('540.00'), start_day + timedelta(days=8)),
            (loc_vijayawada, 'Urad Dal', 10, 'kg', Decimal('1450.00'), start_day + timedelta(days=4)),
            (loc_amaravathi, 'Urad Dal', 6, 'kg', Decimal('900.00'), start_day + timedelta(days=10)),
            (loc_vijayawada, 'Butter', 5, 'kg', Decimal('2350.00'), start_day + timedelta(days=5)),
            (loc_amaravathi, 'Butter', 3, 'kg', Decimal('1440.00'), start_day + timedelta(days=9)),
            (loc_vijayawada, 'Rava (Semolina)', 15, 'kg', Decimal('900.00'), start_day + timedelta(days=2)),
            (loc_amaravathi, 'Rava (Semolina)', 10, 'kg', Decimal('610.00'), start_day + timedelta(days=7)),
            (loc_amaravathi, 'Cooking Oil', 8, 'liter', Decimal('1240.00'), start_day + timedelta(days=11)),
        ]
        for loc_id, name, qty, unit, price, d in purchase_defs:
            purchased_at = datetime.combine(d, dtime(9, 30)) - timedelta(hours=5, minutes=30)
            cur.execute("""
                INSERT INTO store_purchases (location_id, item_name, quantity, unit, price,
                                              purchased_at, recorded_by, master_inventory_id)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM store_purchases
                    WHERE location_id = %s AND item_name = %s AND purchased_at = %s
                )
            """, (loc_id, name, qty, unit, price, purchased_at, recorder_staff, ingredients[name],
                  loc_id, name, purchased_at))

        if args.dry_run:
            conn.rollback()
            print(f'Dry run: {order_ops} orders would be inserted, {usage_ops} usage rows touched. Nothing written.')
        else:
            conn.commit()
            print(f'Seeded: 2 locations, 5 staff, 2 suppliers, {len(ingredients)} ingredients, '
                  f'{len(menu_defs)} menu items (with recipes), {order_ops} orders across 13 days, '
                  f'{usage_ops} daily-usage rows, {len(purchase_defs)} purchases.')
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
