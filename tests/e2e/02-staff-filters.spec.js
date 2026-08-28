const { test, expect } = require('@playwright/test');
const { StaffPage } = require('./staff-page');

test.describe('Staff Management - Filters', () => {
  test.beforeEach(async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.goto();
  });

  test('TC-002: Active/Inactive Staff Status filter shows only matching rows', async ({ page }) => {
    const staff = new StaffPage(page);

    const activeCount = await test.step('Confirm every row starts Active (default tab)', async () => {
      const rows = staff.rows;
      const count = await rows.count();
      expect(count).toBeGreaterThan(0);
      for (let i = 0; i < count; i++) {
        await expect(staff.statusCell(rows.nth(i))).toContainText('Active');
      }
      return count;
    });

    await test.step('Switch to Inactive Staff and confirm only Inactive rows show', async () => {
      await staff.selectStatus('inactive');
      await page.waitForURL(/status=inactive/);
      await expect(staff.statusFilter).toHaveValue('inactive');

      const rows = staff.rows;
      const count = await rows.count();
      expect(count).toBeGreaterThan(0);
      for (let i = 0; i < count; i++) {
        await expect(staff.statusCell(rows.nth(i))).toContainText('Deactive');
        await expect(staff.statusCell(rows.nth(i))).not.toContainText(/^Active$/);
      }
    });

    await test.step('Switch back to Active Staff and confirm the original list is restored', async () => {
      await staff.selectStatus('active');
      await page.waitForURL(/status=active/);
      await expect(staff.statusFilter).toHaveValue('active');
      await expect(staff.rows).toHaveCount(activeCount);
    });
  });

  test('TC-013: All Staff shows both Active and Inactive rows together', async ({ page }) => {
    const staff = new StaffPage(page);

    const activeCount = await test.step('Read the Active count from the default tab', async () => {
      await expect(staff.statusFilter).toHaveValue('active');
      const count = await staff.rows.count();
      return count;
    });

    const inactiveCount = await test.step('Read the Inactive count', async () => {
      await staff.selectStatus('inactive');
      await page.waitForURL(/status=inactive/);
      const count = await staff.rows.count();
      return count;
    });

    await test.step('Switch to All Staff and confirm it shows Active + Inactive combined, with both statuses present', async () => {
      await staff.selectStatus('all');
      await page.waitForURL(/status=all/);
      await expect(staff.statusFilter).toHaveValue('all');

      const rows = staff.rows;
      await expect(rows).toHaveCount(activeCount + inactiveCount);

      const count = await rows.count();
      let sawActive = false;
      let sawInactive = false;
      for (let i = 0; i < count; i++) {
        const text = await staff.statusCell(rows.nth(i)).textContent();
        if (text.includes('Deactive')) sawInactive = true;
        else if (text.includes('Active')) sawActive = true;
      }
      expect(sawActive).toBe(true);
      expect(sawInactive).toBe(true);
    });

    await test.step('Verify the dropdown label shows the combined count', async () => {
      const optionText = await page.locator('#statusFilter option[value="all"]').textContent();
      expect(optionText).toContain(`(${activeCount + inactiveCount})`);
    });
  });

  test('TC-003: Search filters the visible rows by staff name', async ({ page }) => {
    const staff = new StaffPage(page);
    const allRowsBefore = await staff.rows.count();

    await test.step('Search for a name that matches exactly one row', async () => {
      await staff.search('Padmini');
      const visible = staff.visibleRows();
      await expect(visible).toHaveCount(1);
      await expect(visible.first()).toContainText('Padmini');
    });

    await test.step('Search for a name that matches nothing', async () => {
      await staff.search('NoSuchStaffMemberXYZ');
      await expect(staff.visibleRows()).toHaveCount(0);
    });

    await test.step('Clear the search and confirm the full list returns', async () => {
      await staff.search('');
      await expect(staff.visibleRows()).toHaveCount(allRowsBefore);
    });
  });

  test('TC-004: Location filter shows only staff at the selected location', async ({ page }) => {
    const staff = new StaffPage(page);

    const filteredCount = await test.step('Select the first real location and confirm every visible row matches it', async () => {
      const firstLocationOption = staff.locationFilter.locator('option').nth(1);
      const optionValue = await firstLocationOption.getAttribute('value');
      const optionLabel = (await firstLocationOption.textContent()).trim();

      await staff.filterByLocation(optionValue);
      const rows = staff.visibleRows();
      const count = await rows.count();
      expect(count).toBeGreaterThan(0);
      for (let i = 0; i < count; i++) {
        await expect(staff.locationCell(rows.nth(i))).toContainText(optionLabel);
      }
      return count;
    });

    await test.step('Reset to "All Locations" and confirm the full list is restored', async () => {
      await staff.filterByLocation('');
      const allCount = await staff.visibleRows().count();
      expect(allCount).toBeGreaterThanOrEqual(filteredCount);
    });
  });

  test('TC-015: Search and Location filters combine (both must match, not either/or)', async ({ page }) => {
    const staff = new StaffPage(page);

    const locationCount = await test.step('Apply the Location filter alone and note the match count', async () => {
      const firstLocationOption = staff.locationFilter.locator('option').nth(1);
      const optionValue = await firstLocationOption.getAttribute('value');
      await staff.filterByLocation(optionValue);
      const count = await staff.visibleRows().count();
      expect(count).toBeGreaterThan(0);
      return count;
    });

    await test.step('Adding a non-matching Search on top narrows to zero (proves AND, not OR)', async () => {
      await staff.search('NoSuchStaffMemberXYZ');
      await expect(staff.visibleRows()).toHaveCount(0);
    });

    await test.step('Adding a matching Search on top narrows to exactly that one row', async () => {
      await staff.search('');
      const firstRow = staff.visibleRows().first();
      const firstName = (await firstRow.locator('td').nth(1).textContent()).trim().split(/\s+/)[0];

      await staff.search(firstName);
      const rows = staff.visibleRows();
      await expect(rows).toHaveCount(1);
      await expect(rows.first()).toContainText(firstName);
    });

    await test.step('Clearing Search restores the Location-only count', async () => {
      await staff.search('');
      await expect(staff.visibleRows()).toHaveCount(locationCount);
    });
  });
});
