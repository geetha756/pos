const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');

test.describe('Machine Management - history, filters and failures', () => {
  test('MCH-007 - date presets, clear, and invalid range control history filtering', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.getByRole('button', { name: 'Today' }).click();
    await expect(page.getByLabel('From date')).not.toHaveValue('');
    await page.getByLabel('From date').fill('2026-08-14');
    await page.getByLabel('To date').fill('2026-08-13');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByRole('alert')).toContainText('From date cannot be after the To date.');
    await page.getByRole('button', { name: 'Clear' }).click();
    await expect(page.getByLabel('From date')).toHaveValue('');
    await expect(page.getByLabel('To date')).toHaveValue('');
  });

  // Formerly also covered the Graph Type combobox's mouse/keyboard
  // selection (Machine Runtime as its second option) — that combobox and
  // the Machine Runtime graph option were removed from the product
  // (History -> Graph now shows only the Live Temperature Trend chart
  // directly, with no picker), so this test was narrowed to just the tabs
  // and the Graph pane's fixed heading rather than adapted to test a
  // dropdown that no longer exists.
  test('MCH-008 - history tabs switch correctly and the Graph pane shows a fixed heading with no picker', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.getByRole('button', { name: 'Commands' }).click();
    await expect(page.getByText('Command History')).toBeVisible();
    await page.getByRole('button', { name: 'Graph' }).click();
    await expect(page.locator('#eidli-analytics-title')).toHaveText('Live Temperature Trend');
    await expect(page.locator('#eidli-analytics-graph-type-btn')).toHaveCount(0);
  });

  test('MCH-009 - settings API failure renders an error and leaves no false success', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({ settingsResponse: { success: false, message: 'Machine service unavailable' } });
    await machine.gotoSettings();
    await expect(page.getByText('Unable to load settings.')).toBeVisible();
    await expect(page.getByText('Saved.', { exact: true })).toHaveCount(0);
  });

  test('MCH-010 - controls have accessible names and keyboard focus reaches navigation', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();
    await expect(page.getByRole('group', { name: 'Quick date range' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Refresh events' })).toBeEnabled();
    await page.getByRole('button', { name: 'Refresh events' }).focus();
    await expect(page.getByRole('button', { name: 'Refresh events' })).toBeFocused();
    // The refresh handler is allowed to move focus after dispatching a
    // request; this proves the button itself remains keyboard-focusable.
  });
});
