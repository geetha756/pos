const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');

// Fast smoke suite: critical path only. Machines list -> View Machine ->
// Dashboard (temperature/status/heater/sensor) -> History (Events/Commands/
// Analytics load, date filters + custom range + apply + clear + refresh) ->
// Settings loads -> nav works -> no console errors anywhere. Intended to
// run fast and catch a broken build.
//
// The Machine Runtime graph option and the Graph Type combobox used to
// select it were removed from the product (History -> Graph now shows
// only the Live Temperature Trend chart directly, with no picker) — this
// suite's former "graph dropdown works, both options load" loop over
// ['runtime', 'temperature'] was adapted into a check that the Graph tab
// loads cleanly with no dropdown present at all, rather than removed
// outright, since the surrounding critical-path coverage (Graph tab
// loading without error) still applies.
test.describe('Machine Management - SMOKE', () => {
  test('SMK-01 - full critical path loads clean with zero console errors', async ({ page }) => {
    const machine = new MachinePage(page);
    const errors = [];
    const consoleErrors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });

    const events = [
      { id: 1, event_type: 'machine_restarted', created_at: '2026-08-13T02:00:00Z' },
      { id: 2, event_type: 'heater_on', created_at: '2026-08-13T04:40:00Z' },
    ];
    const commands = [{ id: 1, command: 'restart', requested_at: '2026-08-13T02:00:00Z', status: 'success', ack_received_at: '2026-08-13T02:00:05Z' }];
    await machine.installConnectedService({ events, commands });

    // 1. Machines list page loads, card loads
    await page.goto('/machines/');
    await expect(page.getByRole('heading', { name: 'Machines' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Electric Idli Machine' })).toBeVisible();

    // 2. View Machine navigates to Dashboard
    await page.getByRole('link', { name: 'View Machine' }).click();
    await expect(page).toHaveURL(/\/machines\/idli$/);

    // 3. Dashboard: temperature/status/heater/sensor appear
    await expect(page.locator('#eidli-grid-machine')).not.toContainText('—');
    await expect(page.locator('#eidli-grid-heater')).not.toContainText('—');
    await expect(page.locator('#eidli-grid-sensor')).not.toContainText('—');
    await expect(page.getByText('Live Temperature Trend', { exact: true })).toBeVisible();

    // 4. History: Events/Commands/Analytics load
    await page.getByRole('link', { name: 'History' }).click();
    await expect(page).toHaveURL(/\/machines\/idli\/history$/);
    await expect(page.locator('#eidli-events-body')).not.toContainText('Loading');
    await page.getByRole('button', { name: 'Commands' }).click();
    await expect(page.locator('#eidli-commands-body')).not.toContainText('Loading');
    await page.getByRole('button', { name: 'Graph' }).click();
    await expect(page.locator('#eidli-analytics-chart-loading')).toBeHidden({ timeout: 10000 });

    // 5. Graph tab loads cleanly with no graph-type picker (only Live
    // Temperature Trend is offered; the combobox was removed along with
    // Machine Runtime).
    await expect(page.locator('#eidli-analytics-graph-type-btn')).toHaveCount(0);
    await expect(page.locator('#eidli-analytics-title')).toHaveText('Live Temperature Trend');

    // 6. Date filters + custom range + apply + clear + refresh
    await page.getByRole('button', { name: 'Today' }).click();
    await expect(page.getByLabel('From date')).not.toHaveValue('');
    await page.getByRole('button', { name: 'Custom Range' }).click();
    await page.getByLabel('From date').fill('2026-08-01');
    await page.getByLabel('To date').fill('2026-08-13');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.locator('#eidli-hist-range-error')).toBeHidden();
    await page.getByRole('button', { name: 'Clear' }).click();
    await expect(page.getByLabel('From date')).toHaveValue('');
    // Apply/Clear refetch Events/Commands in the background regardless of
    // which History tab is currently visible (see applyDateRange()'s own
    // comment in history.js) — but #eidli-events-refresh only exists in the
    // DOM as visible/clickable while the Events tab pane is actually the
    // one on screen. Step 4 left this test on the Graph (Analytics) tab,
    // so the Events tab must be switched back to before its refresh button
    // can be clicked — clicking it while hidden was the bug that made this
    // test hang until timeout.
    await page.getByRole('button', { name: 'Events' }).click();
    await page.locator('#eidli-events-refresh').click();
    await page.getByRole('button', { name: 'Graph' }).click();
    await page.locator('#eidli-analytics-refresh').click();

    // 7. Settings loads
    await page.getByRole('link', { name: 'Settings' }).click();
    await expect(page).toHaveURL(/\/machines\/idli\/settings$/);
    await expect(page.locator('#eidli-settings-body')).not.toContainText('Loading settings');

    // 8. Critical nav: back button returns to Machines list
    await page.locator('.eidli-shell-back').click();
    await expect(page).toHaveURL(/\/machines\/$/);

    // 9. No console errors anywhere in this flow
    expect(errors).toEqual([]);
  });
});
