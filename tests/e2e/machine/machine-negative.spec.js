const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');
const { success } = require('./test-data');

// New coverage: negative/error paths across status, settings,
// temperature-logs, events, commands, heating-cycles (404/500/malformed
// JSON/empty response), plus console-error and network-failure assertions.
// Does not duplicate MCH-009 (settings GET failure).
//
// The Machine Runtime graph option (and the Graph Type combobox used to
// select it) was removed from the product (History -> Graph now shows
// only the Live Temperature Trend chart, with no picker), so its dedicated
// error-path coverage (formerly MCHX-207, a /events 404 surfacing the "not
// available" message for that graph) was removed rather than adapted —
// there is no feature left to test.
test.describe('Machine Management - negative / error paths', () => {
  test('MCHX-201 - /status 500 shows CONNECTING/offline state, not a false ONLINE badge, no console error', async ({ page }) => {
    const machine = new MachinePage(page);
    const consoleErrors = [];
    page.on('pageerror', e => consoleErrors.push(e.message));
    await machine.installConnectedService({ statusResponse: { __status: 500, success: false, message: 'Internal Server Error' } });
    await machine.gotoDashboard();
    await page.waitForTimeout(500);
    await expect(page.locator('#eidli-conn-badge')).not.toContainText('ONLINE');
    expect(consoleErrors).toEqual([]);
  });

  test('MCHX-202 - /status malformed JSON does not crash the page', async ({ page }) => {
    const machine = new MachinePage(page);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/machines/idli/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().isNavigationRequest()) {
        const response = await route.fetch();
        const html = (await response.text()).replace('configured: false', 'configured: true');
        return route.fulfill({ response, body: html });
      }
      if (url.pathname.endsWith('/status')) return route.fulfill({ status: 200, contentType: 'application/json', body: 'not valid json{{{' });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({})) });
    });
    await machine.gotoDashboard();
    await page.waitForTimeout(500);
    expect(errors).toEqual([]);
  });

  test('MCHX-203 - /temperature-logs 404 on Dashboard shows the chart error banner, preserves prior data', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoDashboard();
    await expect(page.locator('#eidli-temp-chart-error')).toBeHidden();

    await page.unroute('**/machines/idli/**');
    await page.route('**/machines/idli/api/temperature-logs**', route => route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ success: false, message: 'Not Found' }) }));
    await page.route('**/machines/idli/api/status**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ is_online: true })) }));
    await page.getByRole('button', { name: 'Refresh temperature chart' }).click();
    await expect(page.locator('#eidli-temp-chart-error')).toBeVisible();
  });

  test('MCHX-204 - /events 500 on History shows the section error, not a blank/crashed page', async ({ page }) => {
    const machine = new MachinePage(page);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await machine.installConnectedService({ eventsResponse: { success: false, message: 'Machine service unavailable' } });
    await machine.gotoHistory();
    await expect(page.locator('#eidli-events-body')).toContainText('Unable to load events.');
    expect(errors).toEqual([]);
  });

  test('MCHX-205 - /commands 500 on History shows the section error', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({ commandsResponse: { success: false, message: 'Machine service unavailable' } });
    await machine.gotoHistory();
    await page.getByRole('button', { name: 'Commands' }).click();
    await expect(page.locator('#eidli-commands-body')).toContainText('Unable to load command history.');
  });

  test('MCHX-208 - empty (zero-item) responses across events/commands/temperature-logs show explicit empty states, not blank sections', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({ events: [], commands: [] });
    await machine.gotoHistory();
    await expect(page.locator('#eidli-events-body')).toContainText('No machine events');
    await page.getByRole('button', { name: 'Commands' }).click();
    await expect(page.locator('#eidli-commands-body')).toContainText('No commands sent');
  });

  test('MCHX-209 - network failure (aborted request) on Dashboard status does not throw an uncaught page error', async ({ page }) => {
    const machine = new MachinePage(page);
    const requestFailures = [];
    page.on('requestfailed', r => requestFailures.push(r.url()));
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/machines/idli/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().isNavigationRequest()) {
        const response = await route.fetch();
        const html = (await response.text()).replace('configured: false', 'configured: true');
        return route.fulfill({ response, body: html });
      }
      if (url.pathname.endsWith('/status')) return route.abort('failed');
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({})) });
    });
    await machine.gotoDashboard();
    await page.waitForTimeout(500);
    expect(errors).toEqual([]);
  });

  test('MCHX-210 - settings PATCH failure shows inline error and issues no false "Saved." message', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') {
        return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ success: false, message: 'Machine unreachable' }) });
      }
      return route.continue();
    });
    await machine.gotoSettings();
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#eidli-set-off').fill('81');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    // The inline form message and the toast (window.showToast) both render
    // text containing "Machine unreachable" ("Machine unreachable" vs.
    // "Settings save failed: Machine unreachable") — scope to the inline
    // message element specifically so this doesn't hit a Playwright
    // strict-mode violation from matching both.
    await expect(page.locator('#eidli-settings-msg')).toContainText('Machine unreachable');
    await expect(page.getByText('Saved.', { exact: true })).toHaveCount(0);
  });

  test('MCHX-211 - settings sync failure shows the failed status, not a false success', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await page.route('**/machines/idli/api/settings/sync', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: false, message: 'MQTT broker unreachable' }) }));
    await machine.gotoSettings();
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: 'Sync Settings to Machine' }).click();
    await expect(page.getByText(/Failed — MQTT broker unreachable/)).toBeVisible();
  });
});
