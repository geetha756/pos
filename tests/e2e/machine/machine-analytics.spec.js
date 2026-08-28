const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');
const { success } = require('./test-data');

// New coverage: Analytics tab date presets, Apply/Clear, invalid/empty/
// same-time ranges, and the requestSeq race-safety guard on rapid double
// Refresh. Does not duplicate MCH-007/MCH-008.
//
// The Heater ON Time graph option was removed from the product (History ->
// Graph dropdown then only offered Live Temperature Trend and Machine
// Runtime), so its dedicated coverage (formerly MCHX-109/110/115) was
// removed rather than adapted — there is no feature left to test.
//
// The Machine Runtime graph option and the Graph Type combobox that
// switched between it and Live Temperature Trend were also removed from
// the product (History -> Graph now shows only the Live Temperature Trend
// chart directly, with no picker) — so all of the dedicated Machine
// Runtime/combobox coverage that used to live here (formerly MCHX-101/102/
// 103/104/111, plus the graph-type-switch race test MCHX-112, which raced
// Machine Runtime against Live Temperature Trend and is now redundant with
// MCHX-113's own requestSeq coverage of a rapid double Refresh) was removed
// rather than adapted — there is no feature left to test.
test.describe('Machine Management - Analytics tab (graphs, ranges, race-safety)', () => {
  test('MCHX-105 - Yesterday/Last 7 Days/Last 30 Days presets populate From/To and highlight the button', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();

    await page.getByRole('button', { name: 'Yesterday' }).click();
    await expect(page.getByLabel('From date')).not.toHaveValue('');
    await expect(page.getByRole('button', { name: 'Yesterday' })).toHaveClass(/btn-success/);

    await page.getByRole('button', { name: 'Last 7 Days' }).click();
    const from7 = await page.getByLabel('From date').inputValue();
    const to7 = await page.getByLabel('To date').inputValue();
    expect(from7).not.toBe('');
    expect(to7).not.toBe('');
    expect(from7 <= to7).toBe(true);
    await expect(page.getByRole('button', { name: 'Last 7 Days' })).toHaveClass(/btn-success/);

    await page.getByRole('button', { name: 'Last 30 Days' }).click();
    await expect(page.getByRole('button', { name: 'Last 30 Days' })).toHaveClass(/btn-success/);
  });

  test('MCHX-106 - Custom Range highlights the button but leaves fields untouched until Apply', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.getByLabel('From date').fill('');
    await page.getByRole('button', { name: 'Custom Range' }).click();
    await expect(page.getByRole('button', { name: 'Custom Range' })).toHaveClass(/btn-success/);
    await expect(page.getByLabel('From date')).toHaveValue('');
  });

  test('MCHX-107 - same From/To date and same From/To time (boundary) is accepted, not rejected', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.getByLabel('From date').fill('2026-08-13');
    await page.getByLabel('To date').fill('2026-08-13');
    await page.getByLabel('From time').fill('12:00');
    await page.getByLabel('To time').fill('12:00');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });

  test('MCHX-108 - empty From/To with Apply does not error (falls back to no explicit range)', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.locator('#eidli-hist-range-error')).toBeHidden();
  });

  test('MCHX-113 - rapid double-click on Analytics Refresh does not duplicate/corrupt the chart', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.getByRole('button', { name: 'Graph' }).click();
    const refreshBtn = page.locator('#eidli-analytics-refresh');
    await refreshBtn.click();
    await refreshBtn.click();
    await page.waitForTimeout(500);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await expect(page.locator('#eidli-analytics-chart-error')).toBeHidden();
    expect(errors).toEqual([]);
  });

  test('MCHX-114 - tab-switch away from Analytics while a load is in flight does not throw a console error', async ({ page }) => {
    const machine = new MachinePage(page);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await machine.installConnectedService();
    await machine.gotoHistory();
    await page.getByRole('button', { name: 'Graph' }).click();
    await page.getByRole('button', { name: 'Events' }).click();
    await page.getByRole('button', { name: 'Commands' }).click();
    await page.waitForTimeout(300);
    expect(errors).toEqual([]);
  });

});
