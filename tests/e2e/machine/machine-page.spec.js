const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');
const { success } = require('./test-data');

test.describe('Machine Management - dashboard and navigation', () => {
  test('MCH-001 - Machines landing page loads the actual Idli machine card', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('/machines/');
    await expect(page).toHaveURL(/\/machines\/$/);
    await expect(page.getByRole('heading', { name: 'Machines' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Electric Idli Machine' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'View Machine' })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('MCH-002 - View Machine and section navigation open the correct pages', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await page.goto('/machines/');
    await page.getByRole('link', { name: 'View Machine' }).click();
    await expect(page).toHaveURL(/\/machines\/idli$/);
    await expect(page.getByText('Live Temperature Trend', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: 'History' }).click();
    await expect(page).toHaveURL(/\/machines\/idli\/history$/);
    await page.getByRole('link', { name: 'Settings' }).click();
    await expect(page).toHaveURL(/\/machines\/idli\/settings$/);
    await page.locator('.eidli-shell-back').click();
    await expect(page).toHaveURL(/\/machines\/$/);
  });

  test('MCH-003 - dashboard refresh reloads chart data and empty telemetry is explicit', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoDashboard();
    await expect(page.getByRole('button', { name: 'Refresh temperature chart' })).toBeEnabled();
    await page.getByRole('button', { name: 'Refresh temperature chart' }).click();
    await expect(page.locator('#eidli-temp-chart-error')).toBeHidden();

    await page.unroute('**/machines/idli/**');
    await machine.installConnectedService({ settingsResponse: success({}), statusResponse: success({ is_online: true }) });
    await page.route('**/machines/idli/api/temperature-logs**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(success({ items: [], total: 0 })) }));
    await page.reload();
    await expect(page.getByText('No temperature telemetry available yet today.')).toBeVisible();
  });
});
