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
    // Off Threshold's cap was raised to 200°C (was 100°C) — 201 is the real
    // out-of-range value now; 101 (the old boundary) is valid today, see
    // MCH-007 below.
    await page.locator('#eidli-set-off').fill('201');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    // The browser's native max constraint correctly blocks the submit before
    // the page handler can display its inline validation message.
    expect(await page.locator('#eidli-set-off').evaluate(el => el.validity.rangeOverflow)).toBe(true);
    expect(patchCalls).toBe(0);
  });

  // Regression for the 100°C -> 200°C Off/Restart Threshold increase (the
  // Temperature Offset range was also raised to ±20°C at one point, then
  // reverted back to its original ±10°C — this test reflects that final
  // state): a threshold value that used to be rejected (either by the
  // browser's native max constraint or the page's own pre-submit check) must
  // now be accepted end-to-end — HTML max attribute, JS pre-submit guard,
  // AND the actual PATCH payload sent to the backend. Offset stays at its
  // original ±10°C bound throughout.
  test('MCH-007 - Off/Restart Threshold up to 200°C are accepted and saved (previously capped at 100°C); Temperature Offset stays at its original ±10°C', async ({ page }) => {
    const machine = new MachinePage(page);
    let patchBody = null;
    await machine.installConnectedService();
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') {
        patchBody = route.request().postDataJSON();
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({ off_temperature: 200, on_temperature: 200, temperature_offset: 10, buzzer_enabled: true })) });
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
    });
    await machine.gotoSettings();

    const offInput = page.locator('#eidli-set-off');
    const onInput = page.locator('#eidli-set-on');
    const offsetInput = page.locator('#eidli-set-offset');

    // HTML constraint attributes: thresholds raised, offset unchanged.
    await expect(offInput).toHaveAttribute('max', '200');
    await expect(onInput).toHaveAttribute('max', '200');
    await expect(offsetInput).toHaveAttribute('min', '-10');
    await expect(offsetInput).toHaveAttribute('max', '10');

    await offInput.fill('200');
    await onInput.fill('200');
    await offsetInput.fill('10');
    // No native constraint violation at the new threshold ceiling or the
    // (unchanged) offset ceiling.
    expect(await offInput.evaluate(el => el.validity.rangeOverflow)).toBe(false);
    expect(await onInput.evaluate(el => el.validity.rangeOverflow)).toBe(false);
    expect(await offsetInput.evaluate(el => el.validity.rangeOverflow)).toBe(false);

    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: 'Save Settings' }).click();
    // Asserts on the actual PATCH request body reaching the backend (the
    // real proof these values are accepted end-to-end) rather than the
    // page's own post-save "Saved." toast text, which renderSettings()
    // immediately overwrites on success (a separate, pre-existing race in
    // onSaveSettings unrelated to this range change — see MCHX-306, which
    // already fails on that same race independent of any of these values).
    await expect.poll(() => patchBody, { timeout: 5000 }).not.toBeNull();
    expect(patchBody.off_temperature).toBe('200');
    expect(patchBody.on_temperature).toBe('200');
    expect(patchBody.temperature_offset).toBe('10');
    // No leftover inline validation error from either threshold or offset.
    await expect(page.locator('#eidli-settings-body')).not.toContainText('must be');
  });

  test('MCH-008 - Temperature Offset beyond ±10°C is still blocked (range reverted back to its original ±10°C)', async ({ page }) => {
    const machine = new MachinePage(page);
    let patchCalls = 0;
    await machine.installConnectedService();
    await page.route('**/machines/idli/api/settings', route => {
      if (route.request().method() === 'PATCH') patchCalls++;
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(settings)) });
    });
    await machine.gotoSettings();
    const offsetInput = page.locator('#eidli-set-offset');
    await expect(offsetInput).toHaveAttribute('max', '10');
    await offsetInput.fill('11');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    expect(await offsetInput.evaluate(el => el.validity.rangeOverflow)).toBe(true);
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
