const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');
const { success, settings } = require('./test-data');

test.describe('Machine Management - persistence', () => {
  test('MCHP-01 (positive) - saved threshold and buzzer changes use the correct PATCH payload and persist after a page reload', async ({ page }) => {
    const machine = new MachinePage(page);
    // This is deliberately stateful: the intercepted PATCH becomes the
    // backing service state returned by GET after reload, proving the UI
    // renders the persisted server result rather than only its local form.
    let persisted = { ...settings };
    let patchPayload = null;
    await machine.installConnectedService();
    await page.route('**/machines/idli/api/settings', async (route) => {
      if (route.request().method() === 'PATCH') {
        patchPayload = route.request().postDataJSON();
        persisted = {
          ...persisted,
          off_temperature: Number(patchPayload.off_temperature),
          buzzer_enabled: patchPayload.buzzer_enabled,
        };
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(persisted)) });
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(success(persisted)) });
    });

    await machine.gotoSettings();
    await page.locator('#eidli-set-off').fill('81');
    await page.getByLabel('Enabled').uncheck();
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Save Settings' }).click();

    await expect.poll(() => patchPayload, { timeout: 5000 }).not.toBeNull();
    expect(patchPayload).toMatchObject({ off_temperature: '81', buzzer_enabled: false });

    await page.reload();
    await expect(page.locator('#eidli-set-off')).toHaveValue('81');
    await expect(page.getByLabel('Enabled')).not.toBeChecked();
  });
});
