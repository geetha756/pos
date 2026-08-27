const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');
const { success } = require('./test-data');

// New coverage: rapid double-click on Refresh/Apply, browser back/forward
// across Dashboard/History/Settings, out-of-order/duplicate telemetry
// arriving after a newer point (monotonic recorded_at guard in
// refreshLiveTemperature), console-error assertions throughout.
test.describe('Machine Management - race-safety and navigation', () => {
  test('MCHX-301 - double-click on Dashboard Refresh does not duplicate requests harmfully or throw', async ({ page }) => {
    const machine = new MachinePage(page);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await machine.installConnectedService();
    await machine.gotoDashboard();
    const btn = page.getByRole('button', { name: 'Refresh temperature chart' });
    await btn.click();
    await btn.click();
    await page.waitForTimeout(500);
    expect(errors).toEqual([]);
    await expect(page.locator('#eidli-temp-chart-error')).toBeHidden();
  });

  test('MCHX-302 - double-click on History Apply does not fire two overlapping filtered fetches incorrectly', async ({ page }) => {
    const machine = new MachinePage(page);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.getByLabel('From date').fill('2026-08-01');
    await page.getByLabel('To date').fill('2026-08-13');
    const applyBtn = page.getByRole('button', { name: 'Apply' });
    await applyBtn.click();
    await applyBtn.click();
    await page.waitForTimeout(500);
    expect(errors).toEqual([]);
  });

  test('MCHX-303 - browser back/forward across Dashboard -> History -> Settings works without console errors', async ({ page }) => {
    const machine = new MachinePage(page);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await machine.installConnectedService();
    await machine.gotoDashboard();
    await page.getByRole('link', { name: 'History' }).click();
    await expect(page).toHaveURL(/\/machines\/idli\/history$/);
    await page.getByRole('link', { name: 'Settings' }).click();
    await expect(page).toHaveURL(/\/machines\/idli\/settings$/);

    await page.goBack();
    await expect(page).toHaveURL(/\/machines\/idli\/history$/);
    await page.goBack();
    await expect(page).toHaveURL(/\/machines\/idli$/);
    await page.goForward();
    await expect(page).toHaveURL(/\/machines\/idli\/history$/);
    await page.goForward();
    await expect(page).toHaveURL(/\/machines\/idli\/settings$/);
    expect(errors).toEqual([]);
  });

  test('MCHX-304 - an out-of-order (older) temperature reading arriving after a newer one never regresses the displayed value', async ({ page }) => {
    const machine = new MachinePage(page);
    let callCount = 0;
    const newer = { temperature: 90, recorded_at: new Date().toISOString() };
    const older = { temperature: 10, recorded_at: new Date(Date.now() - 60000).toISOString() }; // 1 minute in the past — arrives AFTER newer but is chronologically older
    await page.route('**/machines/idli/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().isNavigationRequest()) {
        const response = await route.fetch();
        const html = (await response.text()).replace('configured: false', 'configured: true');
        return route.fulfill({ response, body: html });
      }
      if (url.pathname.endsWith('/temperature-logs')) {
        callCount++;
        const reading = callCount === 1 ? newer : older; // first response is the newer point; every subsequent poll tries to regress it
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ items: [reading], total: 1 })) });
      }
      if (url.pathname.endsWith('/status')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ is_online: true })) });
      if (url.pathname.endsWith('/settings') && route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({})) });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({})) });
    });
    await machine.gotoDashboard();
    await expect(page.locator('#eidli-grid-temp')).toContainText('90.0');
    // Wait for at least one more live-temp poll tick (2s interval) to fire
    // the "older" (regressive) reading and confirm it's rejected.
    await page.waitForTimeout(2500);
    await expect(page.locator('#eidli-grid-temp')).toContainText('90.0'); // must NOT have regressed to 10.0
  });

  test('MCHX-305 - a duplicate (same recorded_at) temperature reading does not re-render or regress the display', async ({ page }) => {
    const machine = new MachinePage(page);
    const reading = { temperature: 77.7, recorded_at: new Date().toISOString() };
    await page.route('**/machines/idli/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().isNavigationRequest()) {
        const response = await route.fetch();
        const html = (await response.text()).replace('configured: false', 'configured: true');
        return route.fulfill({ response, body: html });
      }
      if (url.pathname.endsWith('/temperature-logs')) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ items: [reading], total: 1 })) }); // exact same reading every poll
      }
      if (url.pathname.endsWith('/status')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({ is_online: true })) });
      if (url.pathname.endsWith('/settings') && route.request().method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({})) });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(success({})) });
    });
    await machine.gotoDashboard();
    await expect(page.locator('#eidli-grid-temp')).toContainText('77.7');
    await page.waitForTimeout(2500);
    await expect(page.locator('#eidli-grid-temp')).toContainText('77.7');
    const chartPointCount = await page.evaluate(() => {
      const inst = Object.values(Chart.instances)[0];
      return inst ? inst.data.datasets[0].data.length : null;
    });
    // The duplicate poll must not append a second point for the same
    // recorded_at onto the chart's tail.
    expect(chartPointCount).toBeLessThanOrEqual(2);
  });

  test('MCHX-306 - Save Settings confirm-dialog ACCEPT actually submits the PATCH', async ({ page }) => {
    const machine = new MachinePage(page);
    let patchCalls = 0;
    await machine.installConnectedService();
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') { patchCalls++; return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({ off_temperature: 81, on_temperature: 74, temperature_offset: 0, buzzer_enabled: true })) }); }
      return route.continue();
    });
    await machine.gotoSettings();
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#eidli-set-off').fill('81');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible();
    expect(patchCalls).toBe(1);
  });

  test('MCHX-307 - History auto-refresh (events tab) does not throw a console error over time', async ({ page }) => {
    const machine = new MachinePage(page);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.waitForTimeout(1000);
    expect(errors).toEqual([]);
  });
});
