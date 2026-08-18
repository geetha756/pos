# Analytics + Recipe Inventory — Production Handoff

Spec for re-applying the work built on `test-pos.snfifteen.com` (repo
`geetha756/pos`, branch `develop`) to the production instance.

> **Read this first.** The most reliable path is **not** re-implementing from
> this document — it is pulling the actual commit. See "Preferred path" below.
> This spec exists for the case where production is a separate codebase that
> has diverged and a manual port is unavoidable.

---

## Preferred path: take the code, don't retype it

All work is on `geetha756/pos` @ `develop`. On production:

```bash
git fetch origin
git log --oneline origin/develop -5        # confirm the commit
git diff HEAD origin/develop --stat        # review before applying
git merge origin/develop                   # or cherry-pick the specific commit
```

Then restart the production service and let the schema auto-migrate (below).
Porting by hand risks silent numeric drift in the reconciliation guarantees
described in "Accuracy contract."

---

## 1. Database schema — three new objects

All three are created automatically on app startup by `create_app()` in
`app.py`. They are idempotent (`IF NOT EXISTS` / `OR REPLACE`) so they are safe
to run against a live database and safe to re-run.

### 1.1 `to_ist()` SQL function
Single source of truth for UTC→IST. Replaces `+ INTERVAL '5 hours 30 minutes'`
copy-pasted into every analytics query.

```sql
CREATE OR REPLACE FUNCTION to_ist(ts TIMESTAMP) RETURNS TIMESTAMP AS $$
    SELECT ts + INTERVAL '5 hours 30 minutes'
$$ LANGUAGE SQL IMMUTABLE;
```
Note: takes `TIMESTAMP`, not `TIMESTAMPTZ`. Call as `to_ist(o.created_at)`.
For `NOW()` you must cast: `to_ist(NOW()::timestamp)`.

### 1.2 `recipe_items` table
Bill-of-materials: how much of each raw ingredient one unit of a menu item
consumes. **Opt-in per menu item** — an item with no rows here is simply not
recipe-tracked, and every consumer silently skips it.

```sql
CREATE TABLE IF NOT EXISTS recipe_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    master_menu_id UUID REFERENCES master_menu(id) ON DELETE CASCADE NOT NULL,
    master_inventory_id UUID REFERENCES master_inventory(id) NOT NULL,
    quantity_per_unit DECIMAL(10,4) NOT NULL CHECK (quantity_per_unit > 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(master_menu_id, master_inventory_id)
);
CREATE INDEX IF NOT EXISTS idx_recipe_items_menu ON recipe_items(master_menu_id);
```

### 1.3 `app_settings` table
Key/value store for business rules that were previously hard-coded in more than
one place.

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO app_settings (key, value) VALUES ('meal_period_morning_end', '13:00')
ON CONFLICT (key) DO NOTHING;
```

### 1.4 Wiring (app.py)
```python
from database import (init_store_purchases_schema, init_analytics_helpers,
                      init_recipe_schema, init_app_settings_schema)
with app.app_context():
    init_security_schema_and_seed()
    init_store_purchases_schema()
    init_analytics_helpers()      # to_ist()
    init_recipe_schema()          # recipe_items
    init_app_settings_schema()    # app_settings
```

### 1.5 No destructive migration required
Nothing drops or alters an existing column. Existing data is untouched.

---

## 2. Shared helpers (`database.py`)

| Helper | Purpose |
|---|---|
| `get_setting(key, default)` | Read one app setting |
| `set_setting(key, value)` | Upsert one app setting |
| `morning_end_time()` | Returns validated `'HH:MM'` morning/evening boundary. **Validates the value before it reaches SQL** (it is interpolated into a `TIME` literal). Falls back to `'13:00'`. |
| `recipe_consumption_ops(location_id, master_menu_id, quantity, staff_id, reference_id, note_prefix)` | Returns `(query, params)` op list that deducts (or, with negative quantity, restores) a menu item's recipe ingredients from location stock. Returns `[]` when the item has no recipe. |

---

## 3. Shared helpers (`routes/inventory.py`)

| Helper | Purpose |
|---|---|
| `_valid_date(raw, fallback)` | Accepts only real `YYYY-MM-DD`; anything else returns fallback. **Required** — without it a malformed `?date_from=` in a bookmarked/crawled URL 500s the page. |
| `_analytics_window()` | Returns `(date_from, date_to, location_filter)`. Validates both dates, and **swaps a reversed range** so from>to shows the range the user meant rather than nothing. |
| `_analytics_where(date_from, date_to, location_filter, alias='o')` | The one WHERE clause every sales query is built on: `status != 'cancelled'` + IST date range + optional location. **This is what guarantees cross-page reconciliation.** |
| `_allocate_stock_ops(...)` | Find-or-create catalog item + add purchased qty to location stock + log transaction. Shared by Add Groceries, manual Purchases, and scanned-bill save. |
| `_daily_sales_consumption(date_from, date_to, location_filter)` | Sales → Recipe → Grocery consumption. Returns `(period_items, period_grocery, days, no_recipe_items)`. |
| `_ingredient_usage_for_menu_item(menu_id, qty)` | One item's recipe × qty sold. |
| `_theoretical_usage` | **REMOVED** — replaced by `_daily_sales_consumption`. |

---

## 4. Routes

### Analytics (all in `routes/inventory.py`, all `@login_required @owner_required`)

| Route | Endpoint | Notes |
|---|---|---|
| `/inventory/analytics` | `analytics` | Hub: KPIs, Daily Revenue chart (click bar → Peak Hours), payment split, revenue by location, 7 launcher tiles |
| `/inventory/analytics/sale-trend` | `analytics_sale_trend` | Revenue/date + `?item=` for per-item units/day + day-of-week average chart |
| `/inventory/analytics/item-trend` | `analytics_item_trend` | Ranked by **quantity**, top item's ingredients inline, click bar → modal |
| `/inventory/analytics/item-trend/<uuid:menu_id>/usage` | `analytics_item_usage` | JSON for the modal |
| `/inventory/analytics/peak-hours` | `analytics_peak_hours` | Hour-by-hour for one date, 24h format, tooltip shows that hour's items |
| `/inventory/analytics/inventory-trend` | `analytics_inventory_trend` | Sales → Recipe → Grocery consumption |
| `/inventory/analytics/stock-runway` | `analytics_stock_runway` | Days left, `?basis=purchase\|14day` |
| `/inventory/analytics/category-mix` | `analytics_category_mix` | **GET+POST** (POST saves the meal boundary). Morning/evening split |
| `/inventory/analytics/profitability` | `analytics_profitability` | Margin from recipe × 90-day avg purchase price |

**Deliberately removed:** `analytics_heatmap`, `analytics_bought_together`
(routes + templates deleted; tiles removed from hub).

### Recipe management (`routes/master_menu.py`)
- `/master-menu/<item_id>/recipe` (GET+POST) — `recipe`
- `/master-menu/<item_id>/recipe/<ingredient_id>/remove` (POST) — `remove_recipe_item`
- "Recipe" button added per row in `templates/master_menu/index.html`

### Modified existing routes
- `routes/orders.py` — `api_create_order`, `edit_order`, `update_status` now
  call `recipe_consumption_ops` inside the **same transaction** as the order
  write. Cancel restores stock; edit reverses then re-applies. Stock is
  **allowed to go negative** (a sale is never blocked by a shortfall).
- `routes/orders.py` `sales_report_pdf` — hard-coded `TIME '13:00:00'` replaced
  with `morning_end_time()`.
- `routes/main.py` — `get_stock_alerts(location_id)` + dashboard banner.
- `routes/main.py` / `routes/inventory.py` — low-stock now uses
  `minimum_stock_level`, **not** the dead `reorder_point`.

---

## 5. Templates

**New:** `analytics_sale_trend.html`, `analytics_item_trend.html`,
`analytics_peak_hours.html`, `analytics_inventory_trend.html`,
`analytics_stock_runway.html`, `analytics_category_mix.html`,
`analytics_profitability.html`, `master_menu/recipe.html`

**Deleted:** `analytics_heatmap.html`, `analytics_bought_together.html`

**Modified:** `analytics.html`, `dashboard.html`, `groceries.html`,
`purchases.html`, `location_inventory.html`, `location_inventory_assign.html`,
`adjust_inventory.html`, `master_menu/index.html`

### 5.1 Card / tile layout (the "Trends" grid on the hub)

Section header, then a Bootstrap grid. **7 tiles**, 4-up on xl:

```html
<div class="mb-2">
  <h5 class="mb-0"><i class="ri-compass-3-line icon me-2"></i>Trends</h5>
  <p class="text-muted small mb-0">Deeper cuts of the same period above — pick one to open its full chart.</p>
</div>
<div class="row g-3 mb-3">
  <div class="col-12 col-md-6 col-xl-3">
    <a href="{{ url_for('inventory.analytics_sale_trend', date_from=date_from, date_to=date_to, location=location_filter) }}"
       class="card h-100 text-decoration-none text-reset analytics-tile">
      <div class="card-body d-flex flex-column align-items-center text-center">
        <span class="analytics-tile-icon" style="background:#2a78d6;"><i class="ri-line-chart-line"></i></span>
        <h6 class="fw-bold mt-3 mb-1">Sale Trend</h6>
        <p class="text-muted small mb-3">Which day of the week sells best</p>
        <span class="btn btn-sm w-100 mt-auto text-white" style="background:#2a78d6;">
          <i class="ri-bar-chart-2-line icon me-1"></i>View Chart</span>
      </div>
    </a>
  </div>
  <!-- repeat per tile -->
</div>
<style>
.analytics-tile:hover { box-shadow: 0 .25rem .75rem rgba(0,0,0,.08); transform: translateY(-1px); transition: all .15s ease; }
.analytics-tile-icon {
  width: 56px; height: 56px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 1.5rem; flex-shrink: 0;
}
</style>
```

Tile colours/icons/subtitles (keep exactly — colours are a CVD-validated set):

| Tile | Colour | Icon | Subtitle |
|---|---|---|---|
| Sale Trend | `#2a78d6` | `ri-line-chart-line` | Which day of the week sells best |
| Item Trend | `#eb6834` | `ri-restaurant-2-line` | Menu items ranked by units sold |
| Peak Hours / Day | `#14a38b` | `ri-time-line` | Hourly breakdown for any single date |
| Inventory Trend | `#7c5cbf` | `ri-archive-2-line` | Ingredients used up the fastest |
| Stock Runway | `#c98500` | `ri-hourglass-line` | Days of stock left per ingredient |
| Revenue by Category | `#4a3aa7` | `ri-pie-chart-2-line` | Which parts of the menu earn |
| Menu Profitability | `#1f9d55` | `ri-funds-line` | Real margin, not just revenue |

### 5.2 Filter row — auto-submit on change (all analytics pages)

Every date input and dropdown carries `onchange="this.form.submit()"`, and the
Apply button stays as an explicit fallback:

```html
<input type="date" id="date_from" name="date_from" class="form-control"
       onchange="this.form.submit()" value="{{ date_from }}">
<select id="location" name="location" class="form-select" onchange="this.form.submit()">
```

Charts use `static/js/chart.umd.min.js` (already vendored — no CDN).
Chart ink `#52514e`, grid `#e1e0d9`.

---

## 6. Key calculations

### Stock Runway
```
window_start = last restock date          (basis=purchase, default)
             | date_to - 13 days          (basis=14day)
consumed     = SUM(daily_inventory_usage.used_quantity) from window_start..date_to
days_elapsed = (window_end - window_start) + 1   |  14
avg_daily    = consumed / days_elapsed
days_left    = current_stock / avg_daily         (None when avg_daily == 0)
```
"Last restock" is a **UNION of both sources** — `store_purchases.purchased_at`
AND `inventory_transactions` where `transaction_type='restock'`. Add Groceries
writes only the latter; keying off purchases alone makes it invisible.

Status: `<2d` critical, `<5d` warning, else good. No consumption → neutral
"no consumption yet" badge, never a fabricated number.

### Revenue by Category
```sql
CASE WHEN to_ist(o.created_at)::time <= TIME %s THEN 'morning' ELSE 'evening' END
```
Boundary comes from `morning_end_time()`. Morning/evening bars are scaled to
**their own category total**, not the whole menu.

### Menu Profitability
```
ingredient_cost = AVG(store_purchases.price / quantity)   -- last 90 days
cost_per_unit   = SUM(recipe.quantity_per_unit * ingredient_cost)
margin_pct      = (avg_selling_price - cost_per_unit) / avg_selling_price
ranked by       = (avg_selling_price - cost_per_unit) * qty_sold
```
Missing recipe OR any ingredient with no recent purchase → "Cost Unknown"
section. Never a guessed number.

### Inventory Trend
```
per item:  ingredient_consumed = recipe.quantity_per_unit * qty_sold
combined:  total per grocery = SUM across every item using it
```
Items with no recipe appear under "Sold Without a Recipe" — never hidden.

---

## 7. Accuracy contract (verify after deploying)

All pages must reconcile to the same total for the same filter. Run:

```sql
-- order-level (analytics home / sale trend / peak hours)
SELECT COUNT(*), COALESCE(SUM(o.total_amount),0) FROM orders o
WHERE o.status != 'cancelled'
  AND DATE(to_ist(o.created_at)) BETWEEN '<from>' AND '<to>';

-- item-level (category mix / item trend) — must equal the above
SELECT COALESCE(SUM(oi.total_price),0) FROM order_items oi
JOIN orders o ON oi.order_id = o.id
WHERE o.status != 'cancelled'
  AND DATE(to_ist(o.created_at)) BETWEEN '<from>' AND '<to>';

-- morning + evening must sum to the item-level total
```
On the test instance these matched exactly (₹13,735.00, zero drift).

---

## 8. Post-deploy checklist

- [ ] Restart the service; confirm the three schema objects were created
- [ ] Every analytics page returns 200 **with an empty date range**
      (`?date_from=2099-01-01&date_to=2099-01-07`) — production may start empty
- [ ] Malformed date returns 200, not 500
      (`?date_from=notadate`) — regression guard for a fixed bug
- [ ] Run the accuracy contract queries above
- [ ] Cancelled orders excluded everywhere
- [ ] **Do NOT run** `scripts/seed_demo_data.py` or
      `scripts/seed_orders_for_current_menu.py` — test fixtures only
- [ ] `scripts/backfill_purchase_stock.py --dry-run` first if production has
      pre-existing unlinked `store_purchases` rows

---

## 9. Known dependencies / limitations

1. **Recipes must be configured** (Master Menu → Recipe) or Inventory Trend,
   Menu Profitability, and recipe-linked stock deduction do nothing. This is
   intentional opt-in, not a bug.
2. **Stock Runway needs Record Usage logged** or it shows "no consumption yet".
3. **Meal boundary is global**, not per-location. Multi-store with different
   hours needs a `location_id` column on `app_settings`.
4. `templates/orders/new.html` still has its own `16:00` default for which menu
   tab opens first. Left deliberately — it is a UI convenience, not a reporting
   rule. Wire it to `morning_end_time()` only if you want them unified.
5. Stock may go **negative** — a sale is never blocked by an inventory
   shortfall. Recorded product decision.
