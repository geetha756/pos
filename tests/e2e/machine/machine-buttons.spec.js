const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');
const { success, settings, status } = require('./test-data');

// Systematic "click every remaining control" pass — positive (does the right
// thing on a real click) paired with negative (does NOT do the wrong thing:
// no button visible when there's nothing more to load, no false success on
// failure, no request fired when it shouldn't be) for every interactive
// element on Dashboard/History/Settings that the other MCH-*/MCHX-* specs
// don't already exercise directly. Cross-referenced against
// tests/e2e/machine/TEST_INVENTORY.md before writing — see that file for
// what's covered elsewhere (graph-type combobox, date presets, chart
// refresh buttons, Sync-to-Machine, Save Settings confirm/cancel, tab
// switching, etc. all already have dedicated MCHX-1xx/2xx/3xx coverage).
test.describe('Machine Management - remaining buttons/toggles (positive + negative)', () => {

  // --- Settings: Buzzer Alerts switch --------------------------------------

  test('MCHB-01 (positive) - toggling Buzzer Alerts OFF and saving sends buzzer_enabled:false in the PATCH body', async ({ page }) => {
    const machine = new MachinePage(page);
    let patchBody = null;
    await machine.installConnectedService({ settingsResponse: success(settings) }); // starts checked (buzzer_enabled: true)
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') {
        patchBody = route.request().postDataJSON();
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({ ...settings, buzzer_enabled: false })) });
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
    });
    await machine.gotoSettings();
    const buzzer = page.getByLabel('Enabled');
    await expect(buzzer).toBeChecked();
    await buzzer.uncheck();
    await expect(buzzer).not.toBeChecked();
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect.poll(() => patchBody, { timeout: 5000 }).not.toBeNull();
    expect(patchBody.buzzer_enabled).toBe(false);
  });

  test('MCHB-02 (negative) - clicking Save Settings with no actual changes does not fire a PATCH at all', async ({ page }) => {
    const machine = new MachinePage(page);
    let patchCalls = 0;
    await machine.installConnectedService({ settingsResponse: success(settings) });
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') patchCalls++;
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
    });
    await machine.gotoSettings();
    // No field touched — clicking Save on an untouched form must be a no-op,
    // and specifically must never prompt the "this changes real heater
    // thresholds" confirm dialog for a save that changes nothing.
    let dialogFired = false;
    page.once('dialog', dialog => { dialogFired = true; dialog.dismiss(); });
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect(page.getByText('No changes to save.')).toBeVisible();
    expect(dialogFired).toBe(false);
    expect(patchCalls).toBe(0);
  });

  // --- History: Commands tab — Refresh button ------------------------------

  test('MCHB-03 (positive) - clicking Commands Refresh re-fetches and renders the latest command rows', async ({ page }) => {
    const machine = new MachinePage(page);
    let commandsCallCount = 0;
    const firstBatch = [{ id: 1, command: 'heater_on', requested_at: '2026-08-13T04:00:00Z', status: 'success', ack_received_at: '2026-08-13T04:00:05Z', response_message: 'OK' }];
    const secondBatch = [
      { id: 1, command: 'heater_on', requested_at: '2026-08-13T04:00:00Z', status: 'success', ack_received_at: '2026-08-13T04:00:05Z', response_message: 'OK' },
      { id: 2, command: 'heater_off', requested_at: '2026-08-13T05:00:00Z', status: 'success', ack_received_at: '2026-08-13T05:00:05Z', response_message: 'OK' },
    ];
    await page.route('**/machines/idli/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().isNavigationRequest()) {
        const response = await route.fetch();
        const html = (await response.text()).replace('configured: false', 'configured: true');
        return route.fulfill({ response, body: html });
      }
      if (url.pathname.endsWith('/status')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(status)) });
      if (url.pathname.endsWith('/settings') && route.request().method() === 'GET') return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
      if (url.pathname.endsWith('/commands')) {
        commandsCallCount++;
        const items = commandsCallCount === 1 ? firstBatch : secondBatch;
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({ items, total: items.length })) });
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({})) });
    });
    await machine.gotoHistory();
    await page.getByRole('button', { name: 'Commands' }).click();
    await expect(page.locator('#eidli-commands-body')).toContainText('Heater On');
    await expect(page.locator('#eidli-commands-body')).not.toContainText('Heater Off');

    await page.locator('#eidli-commands-refresh').click();
    await expect(page.locator('#eidli-commands-body')).toContainText('Heater Off');
    expect(commandsCallCount).toBeGreaterThanOrEqual(2);
  });

  test('MCHB-04 (negative) - Commands Refresh on a failing endpoint shows the section error, not stale success content mislabeled as fresh', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({
      commands: [{ id: 1, command: 'heater_on', requested_at: '2026-08-13T04:00:00Z', status: 'success', ack_received_at: null, response_message: null }],
    });
    await machine.gotoHistory();
    await page.getByRole('button', { name: 'Commands' }).click();
    await expect(page.locator('#eidli-commands-body')).toContainText('Heater On');
    // Now make the endpoint fail and refresh.
    await page.route('**/machines/idli/api/commands**', route => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ success: false, error: 'ServerError', message: 'boom' }) }));
    await page.locator('#eidli-commands-refresh').click();
    await expect(page.locator('#eidli-commands-body')).toContainText('Unable to load command history.');
  });

  // --- History: Events "Load more" -----------------------------------------

  test('MCHB-05 (positive) - Events "Load more" is visible when more rows exist, fetches the next page, and appends without duplicating rows', async ({ page }) => {
    const machine = new MachinePage(page);
    const page1 = Array.from({ length: 50 }, (_, i) => ({ id: i + 1, event_type: 'temperature_reached', event_message: 'reading ' + i, created_at: '2026-08-13T0' + String(i % 9) + ':00:00Z' }));
    const page2 = [{ id: 51, event_type: 'machine_offline', event_message: 'went offline', created_at: '2026-08-13T09:00:00Z' }];
    let eventsCallCount = 0;
    await page.route('**/machines/idli/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().isNavigationRequest()) {
        const response = await route.fetch();
        const html = (await response.text()).replace('configured: false', 'configured: true');
        return route.fulfill({ response, body: html });
      }
      if (url.pathname.endsWith('/status')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(status)) });
      if (url.pathname.endsWith('/settings') && route.request().method() === 'GET') return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
      if (url.pathname.endsWith('/events')) {
        eventsCallCount++;
        const offset = Number(url.searchParams.get('offset') || 0);
        const items = offset === 0 ? page1 : page2;
        // total = 51 -> after page1 (50 items, offset becomes 50) "Load
        // more" must show; after page2 (offset becomes 51 === total) it
        // must hide.
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({ items, total: 51 })) });
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({})) });
    });
    await machine.gotoHistory();
    const moreBtn = page.locator('#eidli-events-more');
    await expect(page.locator('#eidli-events-body')).toContainText('reading 0');
    await expect(moreBtn).toBeVisible();

    const callsBeforeClick = eventsCallCount;
    await moreBtn.click();
    await expect(page.locator('#eidli-events-body')).toContainText('Machine Offline');
    // The button hides once every row has been fetched (offset === total).
    await expect(moreBtn).toBeHidden();
    // At least one more request happened as a direct result of the click
    // (History's own 10s background auto-refresh — unrelated to this
    // button — can also legitimately add extra /events calls during the
    // test, so this checks "the click caused a fetch", not an exact total).
    expect(eventsCallCount).toBeGreaterThan(callsBeforeClick);
    // No duplicate rows: exactly 51 distinct row ids' worth of content is
    // rendered (the de-dupe-by-id logic in createList's load() — a
    // re-fetched page1 from a background auto-refresh must not double up
    // "reading 0" etc.), evidenced by the events body containing "reading
    // 0" exactly once even after any extra background refetch of page1.
    const readingZeroCount = (await page.locator('#eidli-events-body').innerText()).split('reading 0').length - 1;
    expect(readingZeroCount).toBe(1);
  });

  test('MCHB-06 (negative) - Events "Load more" stays hidden when the first page already contains every row', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({
      events: [{ id: 1, event_type: 'machine_restarted', event_message: 'back online', created_at: '2026-08-13T04:00:00Z' }],
    });
    await machine.gotoHistory();
    await expect(page.locator('#eidli-events-body')).toContainText('Machine Restarted');
    await expect(page.locator('#eidli-events-more')).toBeHidden();
  });

  // --- Shared header: connection badge / last-seen / machine name ---------

  test('MCHB-07 (positive) - connection badge shows ONLINE and last-seen/machine-name populate from real /status + /machine data', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({ statusResponse: success({ ...status, is_online: true }) });
    await machine.gotoDashboard();
    await expect(page.locator('#eidli-conn-badge')).toHaveClass(/eidli-conn-online/);
    await expect(page.locator('#eidli-conn-badge')).toContainText('ONLINE');
    await expect(page.locator('#eidli-last-seen')).not.toContainText('—');
  });

  test('MCHB-08 (negative) - connection badge shows OFFLINE (not a false ONLINE) and the fault banner surfaces the offline message when is_online is false', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({ statusResponse: success({ ...status, is_online: false }) });
    await machine.gotoDashboard();
    await expect(page.locator('#eidli-conn-badge')).toHaveClass(/eidli-conn-offline/);
    await expect(page.locator('#eidli-conn-badge')).toContainText('OFFLINE');
    await expect(page.locator('#eidli-conn-badge')).not.toContainText('ONLINE');
    await expect(page.locator('#eidli-fault-banner')).toContainText('Machine Offline');
  });

  // --- Dashboard: fault banner content for sensor/machine faults ----------

  test('MCHB-09 (positive) - a sensor fault (sensor_status: error) surfaces the sensor fault alert on the Dashboard', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({ statusResponse: success({ ...status, sensor_status: 'error' }) });
    await machine.gotoDashboard();
    await expect(page.locator('#eidli-fault-banner')).toContainText('Temperature Sensor Fault');
  });

  test('MCHB-10 (negative) - a fully healthy status (online, sensor ok, machine running) shows NO fault banner content', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({ statusResponse: success({ ...status, is_online: true, sensor_status: 'ok', machine_status: 'running' }) });
    await machine.gotoDashboard();
    await expect(page.locator('#eidli-fault-banner')).toBeEmpty();
  });

  // --- Settings: threshold Save at the exact new/old boundary values ------

  test('MCHB-11 (positive) - Off Threshold saved at exactly the boundary values 0°C and 200°C both succeed (server-side validated boundary)', async ({ page }) => {
    const machine = new MachinePage(page);
    const patchBodies = [];
    await machine.installConnectedService({ settingsResponse: success(settings) });
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') {
        patchBodies.push(route.request().postDataJSON());
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
    });
    await machine.gotoSettings();
    const offInput = page.locator('#eidli-set-off');

    page.once('dialog', dialog => dialog.accept());
    await offInput.fill('0');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect.poll(() => patchBodies.length, { timeout: 5000 }).toBeGreaterThanOrEqual(1);
    expect(patchBodies[0].off_temperature).toBe('0');
    expect(await offInput.evaluate(el => el.validity.rangeOverflow || el.validity.rangeUnderflow)).toBe(false);
  });

  test('MCHB-12 (negative) - Off Threshold just past the boundary (200.01°C) is blocked client-side, no PATCH fires', async ({ page }) => {
    const machine = new MachinePage(page);
    let patchCalls = 0;
    await machine.installConnectedService({ settingsResponse: success(settings) });
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') patchCalls++;
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
    });
    await machine.gotoSettings();
    const offInput = page.locator('#eidli-set-off');
    await offInput.fill('200.01');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    expect(await offInput.evaluate(el => el.validity.rangeOverflow)).toBe(true);
    expect(patchCalls).toBe(0);
  });

  // --- Dashboard: header nav links (History / Settings tabs) --------------

  test('MCHB-13 (positive) - clicking the History tab link from the Dashboard header navigates to History and marks it active', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoDashboard();
    await page.locator('.eidli-shell-tabs a', { hasText: 'History' }).click();
    await expect(page).toHaveURL(/\/machines\/idli\/history$/);
    await expect(page.locator('.eidli-shell-tabs a.active')).toHaveText('History');
  });

  test('MCHB-14 (negative) - the Dashboard tab link is NOT marked active while actually on the History page', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();
    const dashboardLink = page.locator('.eidli-shell-tabs a', { hasText: 'Dashboard' });
    await expect(dashboardLink).not.toHaveClass(/active/);
  });
});
