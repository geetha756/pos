const { test, expect } = require('@playwright/test');
const { StaffPage } = require('./staff-page');

test.describe('Staff Management - View', () => {
  test('TC-005: View displays the correct staff details', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open the Staff List and click View on a known staff member', async () => {
      await staff.goto();
      const row = staff.rowByText('Padmini');
      await expect(row).toBeVisible();
      await staff.clickView(row);
    });

    await test.step('Verify the detail page shows the correct information', async () => {
      await expect(page).toHaveURL(/\/staff\/view\//);
      await expect(page.getByRole('heading', { name: /Padmini/ })).toBeVisible();
      await expect(page.getByText('EMP02', { exact: true })).toBeVisible();
      await expect(page.locator('a[href^="tel:"]')).toContainText('7898455567');
      await expect(page.locator('.badge', { hasText: 'Active' }).first()).toBeVisible();
      await expect(page.getByRole('link', { name: 'Edit Staff Member' })).toBeVisible();
    });
  });
});
