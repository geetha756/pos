const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const path = require('path');
const { StaffPage } = require('./staff-page');

// Positive/negative coverage for the Staff list row-action buttons
// (View/Edit/Deactivate/Activate/Delete), specifically the rule that Edit
// must be completely removed from the DOM (not disabled/greyed) for
// Deactivated/Inactive staff. IDs use a NEW-STF- prefix continuing from
// 07-staff-validation-positive-negative.spec.js's numbering.

function dbGetByEmployeeId(employeeId) {
  const output = execFileSync(
    'python',
    [path.join(__dirname, 'db_helper.py'), 'get-by-employee-id', employeeId],
    { cwd: path.join(__dirname, '..', '..'), encoding: 'utf-8' }
  ).trim();
  return output === 'null' ? null : JSON.parse(output);
}

test.describe.serial('Staff List - Row Action Buttons', () => {
  const FIRST_NAME = 'PWTestFixtureRowActions' + Date.now();
  let employeeId;

  test('NEW-STF-013 (positive): an Active row shows View, Edit, Deactivate, and Delete', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    await staff.fillNewStaff({ firstName: FIRST_NAME, position: 'Cleaning Staff' });
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/$/);

    const row = staff.rowByText(FIRST_NAME);
    await expect(row).toBeVisible();
    employeeId = (await staff.employeeIdCell(row).textContent()).trim();

    await expect(row.getByRole('link', { name: 'View' })).toBeVisible();
    await expect(row.getByRole('link', { name: 'Edit' })).toBeVisible();
    await expect(row.locator('.deactivate-staff-btn')).toBeVisible();
    await expect(row.locator('.delete-staff-btn')).toBeVisible();
    // Never an Activate button while still active.
    await expect(row.getByRole('button', { name: 'Activate', exact: true })).toHaveCount(0);
  });

  test('NEW-STF-014 (negative): Edit is completely absent (not disabled) from a Deactivated row', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.goto();
    const row = staff.rowByText(FIRST_NAME);
    await staff.deactivate(row);
    await expect(page).toHaveURL(/status=active/);
    await staff.waitForScriptsReady();

    await staff.selectStatus('inactive');
    await page.waitForURL(/status=inactive/);
    const inactiveRow = staff.rowByText(FIRST_NAME);
    await expect(inactiveRow).toBeVisible();
    await expect(staff.statusCell(inactiveRow)).toContainText('Deactive');

    // Not just hidden/disabled - genuinely not in the DOM.
    await expect(inactiveRow.getByRole('link', { name: 'Edit' })).toHaveCount(0);
    await expect(inactiveRow.locator('a[href*="/edit/"]')).toHaveCount(0);

    // The rest of the row's actions are still present and correct.
    await expect(inactiveRow.getByRole('link', { name: 'View' })).toBeVisible();
    await expect(inactiveRow.getByRole('button', { name: 'Activate' })).toBeVisible();
    await expect(inactiveRow.locator('.delete-staff-btn')).toBeVisible();
    await expect(inactiveRow.locator('.deactivate-staff-btn')).toHaveCount(0);
  });

  test('NEW-STF-015 (negative): navigating to the Edit URL directly for a deactivated staff member still works (UI hides the button, not the route)', async ({ page }) => {
    const dbRow = dbGetByEmployeeId(employeeId);
    expect(dbRow).not.toBeNull();
    expect(dbRow.is_active).toBe(false);

    // The requirement is a UI-level removal of the Edit *button* - the
    // underlying edit route itself is not required to be blocked, and
    // isn't touched by this change. Confirms this is a deliberate,
    // scoped UI change rather than an accidental route regression.
    await page.goto('/staff/edit/' + dbRow.id);
    await expect(page.getByRole('heading', { name: 'Edit Staff Member' })).toBeVisible();
  });

  test('NEW-STF-016 (positive): re-activating restores Edit and removes Activate', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.goto('?status=inactive');
    const row = staff.rowByText(FIRST_NAME);
    await staff.activate(row);
    await expect(page).toHaveURL(/status=inactive/);
    await staff.waitForScriptsReady();

    await staff.selectStatus('active');
    await page.waitForURL(/status=active/);
    const activeRow = staff.rowByText(FIRST_NAME);
    await expect(activeRow).toBeVisible();
    await expect(staff.statusCell(activeRow)).toContainText('Active');

    await expect(activeRow.getByRole('link', { name: 'Edit' })).toBeVisible();
    await expect(activeRow.locator('.deactivate-staff-btn')).toBeVisible();
    await expect(activeRow.getByRole('button', { name: 'Activate', exact: true })).toHaveCount(0);
  });

  test('NEW-STF-017 (positive): Delete is available on both Active and Inactive rows, and soft-deletes correctly', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.goto();
    const row = staff.rowByText(FIRST_NAME);
    await expect(row.locator('.delete-staff-btn')).toBeVisible();
    await staff.delete(row);
    await expect(page).toHaveURL(/status=active/);
    await expect(staff.rowByText(FIRST_NAME)).toHaveCount(0);

    const dbRow = dbGetByEmployeeId(employeeId);
    expect(dbRow.is_deleted).toBe(true);
  });
});
