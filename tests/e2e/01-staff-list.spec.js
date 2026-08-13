const { test, expect } = require('@playwright/test');
const { StaffPage } = require('./staff-page');

test.describe('Staff Management - Staff List', () => {
  test('TC-001: Staff List loads with expected columns, heading, and default Active Staff tab', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open the Staff Management list', async () => {
      await staff.goto();
      await expect(page.getByRole('heading', { name: 'Staff Management' })).toBeVisible();
    });

    await test.step('Verify the table columns', async () => {
      const headers = staff.table.locator('thead th');
      await expect(headers).toHaveText([
        'Employee ID', 'Name', 'Position', 'Department', 'Location', 'Status', 'Actions',
      ]);
    });

    await test.step('Verify Active Staff is the default selected tab', async () => {
      await expect(staff.statusFilter).toHaveValue('active');
    });

    await test.step('Verify every visible row is Active, and the count matches the tab badge', async () => {
      const rows = staff.rows;
      const count = await rows.count();
      expect(count).toBeGreaterThan(0);
      for (let i = 0; i < count; i++) {
        await expect(staff.statusCell(rows.nth(i))).toContainText('Active');
        await expect(staff.statusCell(rows.nth(i))).not.toContainText('Inactive');
      }

      const optionText = await page.locator('#statusFilter option[value="active"]').textContent();
      const match = optionText.match(/\((\d+)\)/);
      expect(match).not.toBeNull();
      expect(count).toBe(Number(match[1]));
    });

    await test.step('Verify View/Edit actions are present on each row', async () => {
      const firstRow = staff.rows.first();
      await expect(firstRow.getByRole('link', { name: 'View' })).toBeVisible();
      await expect(firstRow.getByRole('link', { name: 'Edit' })).toBeVisible();
    });
  });

  test('TC-014: Staff List is ordered by Employee ID ascending, not insertion or name order', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open All Staff so every row (both statuses) is visible', async () => {
      await staff.goto('?status=all');
      await expect(staff.statusFilter).toHaveValue('all');
    });

    await test.step('Verify Employee IDs appear in strict ascending numeric order', async () => {
      const count = await staff.rows.count();
      expect(count).toBeGreaterThan(1);

      const employeeIds = [];
      for (let i = 0; i < count; i++) {
        employeeIds.push((await staff.employeeIdCell(staff.rows.nth(i)).textContent()).trim());
      }

      const numericParts = employeeIds.map((id) => {
        const m = id.match(/(\d+)$/);
        expect(m).not.toBeNull();
        return Number(m[1]);
      });
      const sorted = [...numericParts].sort((a, b) => a - b);
      expect(numericParts).toEqual(sorted);
    });
  });
});
