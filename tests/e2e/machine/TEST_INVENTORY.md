# Electric Idli Machine — Test Inventory

Catalog of every discovered interactive element / page / API route in the Electric Idli
Machine module, each assigned a unique Test ID. "Covered" cites the existing MCH-### spec
that already exercises it; "Uncovered" items are addressed by the new specs added in this
audit (IDs prefixed `EID-` for unit tests, `MCHX-` for new Playwright E2E, `SMK-` for smoke,
`MCHB-` for the later positive/negative "every button" pass in machine-buttons.spec.js —
Buzzer switch, Commands refresh + Events/Commands Load-more, connection badge ONLINE/
OFFLINE, fault-banner content, threshold Save at its exact 0°C/200°C boundary, and
header nav-link active-state).

Sources inspected: `pos/templates/machines/*.html`, `pos/static/js/eidli/*.js`,
`pos/routes/machines.py`, `pos/tests/e2e/machine/*`.

## Pages / Routes

| ID | Element | Route | Covered By | Notes |
|----|---------|-------|-----------|-------|
| PG-01 | Machines list/dashboard page | `GET /machines/` | MCH-001 | |
| PG-02 | Idli Dashboard page | `GET /machines/idli` | MCH-002, MCH-003 | |
| PG-03 | Idli History page | `GET /machines/idli/history` | MCH-002, MCH-007, MCH-008, MCH-010 | |
| PG-04 | Idli Settings page | `GET /machines/idli/settings` | MCH-002, MCH-004..006, MCH-009 | |

## API Routes (pos/routes/machines.py)

| ID | Route | Method | Covered By | Notes |
|----|-------|--------|-----------|-------|
| API-01 | `/idli/api/machine` | GET | Indirect (header name) | Uncovered: failure path |
| API-02 | `/idli/api/status` | GET | MCH-003,004 (mocked) | Uncovered: 404/500/timeout/malformed |
| API-03 | `/idli/api/settings` | GET | MCH-004, MCH-009 | |
| API-04 | `/idli/api/settings` | PATCH | MCH-005, MCH-006 | validation covered client-side only |
| API-05 | `/idli/api/temperature-logs` | GET | MCH-003 (empty case) | Uncovered: 404/500/malformed |
| API-06 | `/idli/api/events` | GET | Indirect | Uncovered: 404/500/malformed, event_type filter |
| API-07 | `/idli/api/commands` | GET | Indirect | Uncovered: 404/500/malformed |
| API-08 | `/idli/api/restart` | POST | None | Uncovered — no UI trigger found in templates (dead route or future) |
| API-09 | `/idli/api/settings/sync` | POST | MCH-006 | |
| API-10 | `/idli/api/sessions/*` | GET | None | Backend confirmed 404 per history-analytics.js comments; not used by any UI |
| API-11 | `/idli/api/heating-cycles` | GET | None | Uncovered: used by Analytics "Heater ON Time" |
| Server validation | `_validate_threshold`, `_validate_range` (0-100°C, -10..10 offset) | N/A | None (server-side) | Uncovered — client validation (MCH-005) blocks before reaching server; server path unexercised by any E2E test |

## Dashboard page (idli.html) elements

| ID | Element | Selector | Covered | Notes |
|----|---------|----------|---------|-------|
| DB-01 | Fault banner (offline/sensor fault/machine fault) | `#eidli-fault-banner` | MCHB-08, MCHB-09, MCHB-10 | |
| DB-02 | Machine status badge | `#eidli-grid-machine` | Indirect | |
| DB-03 | Temperature value | `#eidli-grid-temp` | Indirect | |
| DB-04 | Heater badge | `#eidli-grid-heater` | Indirect | |
| DB-05 | Sensor badge | `#eidli-grid-sensor` | Indirect | |
| DB-06 | Threshold display (off/restart) | `#eidli-threshold-off`, `#eidli-threshold-restart` | Uncovered | |
| DB-07 | Live Temperature Trend chart | `#eidli-temp-chart` | MCH-002 (visible only) | Uncovered: Chart.js instance data assertions |
| DB-08 | Refresh temperature chart button | `#eidli-temp-refresh` | MCH-003 | |
| DB-09 | Chart empty state | `#eidli-temp-chart-empty` | MCH-003 | |
| DB-10 | Chart error state | `#eidli-temp-chart-error` | Uncovered | |
| DB-11 | Chart loading overlay | `#eidli-temp-chart-loading` | Uncovered | |

## History page (idli_history.html) elements

| ID | Element | Selector | Covered | Notes |
|----|---------|----------|---------|-------|
| HI-01 | Quick range: Today | `[data-preset=today]` | MCH-007 | |
| HI-02 | Quick range: Yesterday | `[data-preset=yesterday]` | Uncovered | |
| HI-03 | Quick range: Last 7 Days | `[data-preset=week]` | Uncovered | |
| HI-04 | Quick range: Last 30 Days | `[data-preset=month]` | Uncovered | |
| HI-05 | Quick range: Custom Range | `[data-preset=custom]` | Uncovered | |
| HI-06 | From date input | `#eidli-hist-from-date` | MCH-007 | |
| HI-07 | From time input | `#eidli-hist-from-time` | Uncovered | |
| HI-08 | To date input | `#eidli-hist-to-date` | MCH-007 | |
| HI-09 | To time input | `#eidli-hist-to-time` | Uncovered | |
| HI-10 | Apply button | `#eidli-hist-apply` | MCH-007 | |
| HI-11 | Clear button | `#eidli-hist-clear` | MCH-007 | |
| HI-12 | Range validation error banner | `#eidli-hist-range-error` | MCH-007 (From>To only) | Uncovered: same start/end, empty values |
| HI-13 | Events tab | `[data-tab=events]` | MCH-008 (default) | |
| HI-14 | Commands tab | `[data-tab=commands]` | MCH-008 | |
| HI-15 | Analytics tab | `[data-tab=analytics]` | MCH-008 | |
| HI-16 | Events refresh button | `#eidli-events-refresh` | MCH-010 (focus only) | Uncovered: click/reload behavior |
| HI-17 | Events "Load more" button | `#eidli-events-more` | MCHB-05, MCHB-06 | |
| HI-18 | Commands refresh button | `#eidli-commands-refresh` | MCHB-03, MCHB-04 | |
| HI-19 | Commands "Load more" button | `#eidli-commands-more` | Uncovered | Same createList() code path as HI-17 (MCHB-05/06); not separately exercised |
| HI-20 | Graph Type combobox trigger | `#eidli-analytics-graph-type-btn` | MCH-008 (keyboard, 1 option) | Uncovered: mouse selection, 3rd option, Home/End/Escape/outside-click |
| HI-21 | Graph Type option: Live Temperature Trend | `[data-value=temperature]` | Default state | |
| HI-22 | Graph Type option: Machine Runtime | `[data-value=runtime]` | MCH-008 | |
| HI-23 | Graph Type option: Heater ON Time | `[data-value=heater]` | Uncovered | |
| HI-24 | Analytics refresh button | `#eidli-analytics-refresh` | Uncovered | |
| HI-25 | Analytics chart canvas | `#eidli-analytics-chart` | Uncovered | Chart.js instance assertions |
| HI-26 | Analytics summary strip | `#eidli-analytics-summary` | Uncovered | |
| HI-27 | Analytics empty state | `#eidli-analytics-chart-empty` | Uncovered | |
| HI-28 | Analytics error state | `#eidli-analytics-chart-error` | Uncovered | |

## Settings page (idli_settings.html) elements

| ID | Element | Selector | Covered | Notes |
|----|---------|----------|---------|-------|
| ST-01 | Off Threshold input | `#eidli-set-off` | MCH-004, MCH-005 | |
| ST-02 | Restart Threshold input | `#eidli-set-on` | MCH-004 | |
| ST-03 | Temperature Offset input | `#eidli-set-offset` | Uncovered | |
| ST-04 | Buzzer Enabled switch | `#eidli-set-buzzer` | MCHB-01 | |
| ST-05 | Save Settings button | submit | MCH-005, MCH-006 | |
| ST-06 | Save confirm dialog (accept) | `confirm()` | Uncovered (only dismiss tested in MCH-006) | |
| ST-07 | Sync Settings to Machine button | `#eidli-settings-sync-btn` | MCH-004 (disabled), MCH-006 (enabled+click) | |
| ST-08 | Sync status text | `#eidli-sync-status` | MCH-006 | |
| ST-09 | Settings load error | `#eidli-settings-body .eidli-section-error` | MCH-009 | |

## Shared header / nav (_idli_nav.html + core.js)

| ID | Element | Covered | Notes |
|----|---------|---------|-------|
| NV-01 | Connection badge (online/offline/connecting) | MCHB-07, MCHB-08 | |
| NV-02 | Last-seen text | MCHB-07 | |
| NV-03 | Machine name | Indirect (page loads, not separately asserted) | |
| NV-04 | Clock | Uncovered (non-deterministic, low value) | |
| NV-05 | Back button | MCH-002 | |
| NV-06 | History link | MCH-002 | |
| NV-07 | Settings link | MCH-002 | |

## Pure/testable JS functions (unit-test candidates)

| ID | Function | File | Covered | Notes |
|----|----------|------|---------|-------|
| FN-01 | `splitSpanByDay` | history-analytics.js | Uncovered | Midnight-crossing split — highest priority |
| FN-02 | `bucketSpansByDay` | history-analytics.js | Uncovered | |
| FN-03 | `dailyChartData` | history-analytics.js | Uncovered | |
| FN-04 | `buildOnlineSpans` | history-analytics.js | Uncovered | dup ON/OFF, stray OFF, ongoing span |
| FN-05 | `resolveBounds` | history-analytics.js | Uncovered | empty range, From>To defensive path |
| FN-06 | `fmtDurationHM` | history-analytics.js | Uncovered | boundary: 0, <1m, exact hour |
| FN-07 | `aggregateSlice` | history-analytics.js / dashboard.js | Uncovered | malformed/NaN temps |
| FN-08 | `validateDateRange` | history.js | Uncovered | From>To, same day time>time, empty |
| FN-09 | `istDateISO` / `fmtRelative` / `fmtDuration` / `fmtTemp` | core.js | Uncovered | null/malformed input |
| FN-10 | badge functions (heaterBadge, sensorBadge, machineStateBadge, etc.) | core.js | Uncovered | unknown/null status handling |
| FN-11 | `computeStableYBounds` | dashboard.js | Uncovered | |

## Negative / error-path scenarios

| ID | Scenario | Covered | Notes |
|----|---------|---------|-------|
| NEG-01 | `/status` 404/500/timeout/malformed JSON | Uncovered | |
| NEG-02 | `/settings` GET failure | MCH-009 | |
| NEG-03 | `/temperature-logs` 404/500/malformed | Uncovered | |
| NEG-04 | `/events` 404/500/malformed | Uncovered | |
| NEG-05 | `/commands` 404/500/malformed | Uncovered | |
| NEG-06 | `/heating-cycles` 404/500/malformed | Uncovered | |
| NEG-07 | Rapid double-click Refresh (dashboard) | Uncovered | |
| NEG-08 | Rapid double-click Apply (history) | Uncovered | |
| NEG-09 | Switch graph type mid-flight — stale response must not overwrite (requestSeq guard) | Uncovered | Critical race-safety test |
| NEG-10 | Tab switch while loading | Uncovered | |
| NEG-11 | Browser back/forward across Dashboard/History/Settings | Uncovered | |
| NEG-12 | Out-of-order/duplicate temperature reading arriving late | Uncovered | monotonic guard in refreshLiveTemperature |

## Boundary scenarios

| ID | Scenario | Covered | Notes |
|----|----------|---------|-------|
| BND-01 | 10:10 AM → 3:14 PM single cycle crossing multiple hour boundaries = 5h04m, never double-counted | Uncovered | THE key regression per spec |
| BND-02 | Cycle crossing midnight split across 2 IST days | Uncovered | |
| BND-03 | Ongoing cycle (`heater_off_at: null`) clipped at "now" | Uncovered | |
| BND-04 | From date == To date (single-day boundary) | Uncovered | |
| BND-05 | From time == To time same day | Uncovered | |
| BND-06 | Empty From/To (defaults to "today") | Uncovered | |
| BND-07 | on_temperature / off_temperature exactly 0 and 200 | Uncovered | server _validate_threshold boundary (raised from 100 to 200) |
| BND-08 | temperature_offset exactly -10 / 10 | Covered (MCH-008) | server _validate_range boundary (raised to ±20 then reverted to its original ±10) |

Legend: **Covered** = an existing MCH-001..010 spec already exercises this element/path.
**Uncovered** = addressed by new specs added in this audit (see final report for file paths),
OR marked BLOCKED in the Excel report when it structurally requires a live backend/DB/hardware.
