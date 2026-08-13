const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');
const { success, settings } = require('./test-data');

test.describe('Machine Management - settings controls', () => {
  test('MCH-004 - settings form exposes real inputs, switch and disabled offline sync action', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({ statusResponse: success({ is_online: false }), settingsResponse: success(settings) });
    await machine.gotoSettings();
    await expect(page.locator('#eidli-set-off')).toHaveValue('82');
    await expect(page.locator('#eidli-set-on')).toHaveValue('74');
    await expect(page.getByLabel('Enabled')).toBeChecked();
    await expect(page.getByRole('button', { name: 'Sync Settings to Machine' })).toBeDisabled();
  });

  test('MCH-005 - validation blocks out-of-range settings without an API update', async ({ page }) => {
    const machine = new MachinePage(page);
    let patchCalls = 0;
    await machine.installConnectedService();
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') patchCalls++;
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
    });
    await machine.gotoSettings();
    await page.locator('#eidli-set-off').fill('101');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    // The browser's native max constraint correctly blocks the submit before
    // the page handler can display its inline validation message.
    expect(await page.locator('#eidli-set-off').evaluate(el => el.validity.rangeOverflow)).toBe(true);
    expect(patchCalls).toBe(0);
  });

  test('MCH-006 - save confirmation cancellation preserves settings and sync confirmation dispatches once', async ({ page }) => {
    const machine = new MachinePage(page);
    let patchCalls = 0, syncCalls = 0;
    await machine.installConnectedService();
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') patchCalls++;
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
    });
    await page.route('**/machines/idli/api/settings/sync', route => { syncCalls++; return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({ request_id: null })) }); });
    await machine.gotoSettings();
    page.once('dialog', dialog => dialog.dismiss());
    await page.locator('#eidli-set-off').fill('81');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    expect(patchCalls).toBe(0);
    await expect(page.getByRole('button', { name: 'Sync Settings to Machine' })).toBeEnabled();
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: 'Sync Settings to Machine' }).click();
    await expect(page.getByText('Sent — command accepted.')).toBeVisible();
    expect(syncCalls).toBe(1);
  });
});
