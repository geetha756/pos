const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const path = require('path');
const { StaffPage } = require('./staff-page');

// This whole file operates on ONE dedicated staff member created here (not
// the shared seeded rows other spec files read), so every mutating test
// stays isolated and independently re-runnable. Ends the run Deleted (see
// TC-012) - both Deactivate and Delete are soft, non-destructive status
// changes (is_active / is_deleted flags), so the row is never actually gone;
// there's no hard-delete UI in this app to clean it up with either way.
const FIXTURE_FIRST_NAME = 'PWTestFixture' + Date.now();
let fixtureEmployeeId;

function dbGetByEmployeeId(employeeId) {
  const output = execFileSync(
    'python',
    [path.join(__dirname, 'db_helper.py'), 'get-by-employee-id', employeeId],
    { cwd: path.join(__dirname, '..', '..'), encoding: 'utf-8' }
  ).trim();
  return output === 'null' ? null : JSON.parse(output);
}

test.describe.serial('Staff Management - Edit, Phone Validation, Status Change, Soft Delete', () => {
  test('TC-006: Add Staff Member succeeds with Last Name and Phone provided', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Add Staff Member', async () => {
      await staff.gotoAdd();
      await expect(page.getByRole('heading', { name: 'Add Staff Member' })).toBeVisible();
    });

    await test.step('Fill First Name, Last Name, Phone, and Position, then submit', async () => {
      await staff.fillNewStaff({ firstName: FIXTURE_FIRST_NAME, lastName: 'Fixture', phone: '9000000001', position: 'Cleaning Staff' });
      await staff.submit();
    });

    await test.step('Verify the new staff member appears in the Active Staff list', async () => {
      await expect(page).toHaveURL(/\/staff\/$/);
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await expect(row).toBeVisible();
      fixtureEmployeeId = (await staff.employeeIdCell(row).textContent()).trim();
      expect(fixtureEmployeeId).toMatch(/^EMP\d+$/);
    });

    await test.step('Verify in the database: record active, Last Name and Phone stored correctly', async () => {
      const dbRow = dbGetByEmployeeId(fixtureEmployeeId);
      expect(dbRow).not.toBeNull();
      expect(dbRow.is_active).toBe(true);
      expect(dbRow.last_name).toBe('Fixture');
      expect(dbRow.phone).toBe('9000000001');
    });
  });

  test('TC-007: Edit updates and persists staff details', async ({ page }) => {
    const staff = new StaffPage(page);
    const marker = 'Updated by Playwright E2E - ' + Date.now();

    await test.step('Open Edit for the fixture staff member and change Notes', async () => {
      await staff.goto();
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await staff.clickEdit(row);
      await expect(page.getByRole('heading', { name: 'Edit Staff Member' })).toBeVisible();
      await staff.notesInput.fill(marker);
      // Bank Account Number, IFSC Code, and Monthly Salary are required on
      // Edit (Add Staff Member never collected them for this fixture), so
      // any Edit save needs valid values here regardless of which field the
      // test is actually exercising.
      await staff.bankAccountInput.fill('123456789012');
      await staff.ifscInput.fill('SBIN0005814');
      await staff.monthlySalaryInput.fill('25000');
      await staff.submit();
    });

    await test.step('Re-open Edit and verify the change persisted server-side', async () => {
      await expect(page).toHaveURL(/\/staff\/$/);
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await staff.clickEdit(row);
      await expect(staff.notesInput).toHaveValue(marker);
    });
  });

  test('TC-008: Phone validation enforces digits-only, 10-digit numbers', async ({ page }) => {
    const staff = new StaffPage(page);
    // A small per-keystroke delay so each 'input' event (including the
    // native reportValidity() bubble the app triggers on a bad character)
    // fully resolves before the next key lands - matches real typing speed;
    // Playwright's default zero-delay typing fires faster than that can
    // keep up with and drops/races events.
    const TYPE_OPTS = { delay: 30 };

    await test.step('Open Edit for the fixture staff member', async () => {
      await staff.goto();
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await staff.clickEdit(row);
      // The Edit page's own inline <script> (phone input-stripping
      // listener) executes as the browser parses the bottom of the page -
      // clicking the Edit link only guarantees the URL changed, not that
      // parsing/execution has finished. Interacting with #phone before it
      // has would silently type into a page with no listener attached yet.
      await staff.waitForScriptsReady();
    });

    await test.step('Letters mixed with digits are stripped live - only digits remain', async () => {
      await staff.phoneInput.fill('');
      await staff.phoneInput.pressSequentially('abc12de34', TYPE_OPTS);
      await expect(staff.phoneInput).toHaveValue('1234');
    });

    await test.step('More than 10 digits gets capped at 10', async () => {
      await staff.phoneInput.fill('');
      await staff.phoneInput.pressSequentially('123456789012', TYPE_OPTS);
      await expect(staff.phoneInput).toHaveValue('1234567890');
    });

    await test.step('An incomplete (non-10-digit) phone blocks submission via validation', async () => {
      // NOTE: <form id="staffForm"> has no `novalidate`, so the browser's
      // own native constraint validation intercepts before the page's
      // 'submit' handler ever runs - the custom
      // "Phone number must be exactly 10 digits." <div class="invalid-feedback">
      // text never actually renders on a real submit attempt (the browser's
      // generic built-in validation bubble shows instead). Submission is
      // still correctly blocked either way, which is what's asserted here -
      // the pattern-mismatch state itself (:invalid pseudo-class) is the
      // reliable, real signal. Documented as a finding, app code untouched.
      await staff.phoneInput.fill('12345');
      await staff.submit();
      await expect(page).toHaveURL(/\/staff\/edit\//); // still on the Edit page - submission was blocked
      await expect(page.locator('#phone:invalid')).toHaveCount(1);
    });

    await test.step('A valid 10-digit phone saves successfully', async () => {
      await staff.phoneInput.fill('9000000099');
      await staff.submit();
      await expect(page).toHaveURL(/\/staff\/$/);
    });

    await test.step('Verify the saved phone number in the database', async () => {
      const dbRow = dbGetByEmployeeId(fixtureEmployeeId);
      expect(dbRow.phone).toBe('9000000099');
    });
  });

  test('TC-009: Deactivate performs a status change to Inactive Staff', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Deactivate the fixture staff member from the Active tab', async () => {
      await staff.goto();
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await expect(row).toBeVisible();
      await staff.openDeactivateModal(row);
      await expect(staff.deactivateModal).toContainText(FIXTURE_FIRST_NAME);
      await staff.confirmDeactivate();
      await expect(page).toHaveURL(/status=active/);
      await expect(staff.rowByText(FIXTURE_FIRST_NAME)).toHaveCount(0);
    });

    await test.step('Verify it now shows under Inactive Staff with an Activate action', async () => {
      await staff.waitForScriptsReady();
      await staff.selectStatus('inactive');
      await page.waitForURL(/status=inactive/);
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await expect(row).toBeVisible();
      await expect(staff.statusCell(row)).toContainText('Inactive');
      await expect(row.getByRole('button', { name: 'Activate' })).toBeVisible();
    });

    await test.step('Verify is_active = false in the database', async () => {
      const dbRow = dbGetByEmployeeId(fixtureEmployeeId);
      expect(dbRow.is_active).toBe(false);
    });
  });

  test('TC-010: Activate performs a status change back to Active Staff', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Activate the fixture staff member from the Inactive tab', async () => {
      await staff.goto('?status=inactive');
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await expect(row).toBeVisible();
      await staff.activate(row);
      await expect(page).toHaveURL(/status=inactive/); // redirected back to the tab the action was taken from
      await expect(staff.rowByText(FIXTURE_FIRST_NAME)).toHaveCount(0);
    });

    await test.step('Verify it now shows back under Active Staff', async () => {
      await staff.waitForScriptsReady();
      await staff.selectStatus('active');
      await page.waitForURL(/status=active/);
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await expect(row).toBeVisible();
      await expect(staff.statusCell(row)).toContainText('Active');
    });

    await test.step('Verify is_active = true in the database', async () => {
      const dbRow = dbGetByEmployeeId(fixtureEmployeeId);
      expect(dbRow.is_active).toBe(true);
    });
  });

  test('TC-011: Deactivate is a soft delete - record remains in the database', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Deactivate the fixture staff member once more', async () => {
      await staff.goto();
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await staff.deactivate(row);
      await expect(page).toHaveURL(/status=active/);
      await expect(staff.rowByText(FIXTURE_FIRST_NAME)).toHaveCount(0);
      await staff.waitForScriptsReady();
    });

    await test.step('Query the database directly: row still exists, only is_active flipped', async () => {
      const dbRow = dbGetByEmployeeId(fixtureEmployeeId);
      expect(dbRow).not.toBeNull();
      expect(dbRow.employee_id).toBe(fixtureEmployeeId);
      expect(dbRow.is_active).toBe(false);
    });

    await test.step('Verify it is still reachable in the app under Inactive Staff', async () => {
      await staff.selectStatus('inactive');
      await page.waitForURL(/status=inactive/);
      await expect(staff.rowByText(FIXTURE_FIRST_NAME)).toBeVisible();
    });
  });

  test('TC-012: Delete is a soft delete - hidden from both tabs, but the record remains in the database', async ({ page }) => {
    const staff = new StaffPage(page);
    let staffId;

    await test.step('Delete the fixture staff member from the Inactive tab', async () => {
      await staff.goto('?status=inactive');
      const row = staff.rowByText(FIXTURE_FIRST_NAME);
      await expect(row).toBeVisible();
      staffId = await row.locator('.delete-staff-btn').getAttribute('data-staff-id');
      await staff.delete(row);
      await expect(page).toHaveURL(/status=inactive/);
      await expect(staff.rowByText(FIXTURE_FIRST_NAME)).toHaveCount(0);
    });

    await test.step('Verify it does not reappear under Active Staff either', async () => {
      await staff.waitForScriptsReady();
      await staff.selectStatus('active');
      await page.waitForURL(/status=active/);
      await expect(staff.rowByText(FIXTURE_FIRST_NAME)).toHaveCount(0);
    });

    await test.step('Query the database directly: row still exists, is_deleted = true, is_active = false', async () => {
      const dbRow = dbGetByEmployeeId(fixtureEmployeeId);
      expect(dbRow).not.toBeNull();
      expect(dbRow.employee_id).toBe(fixtureEmployeeId);
      expect(dbRow.is_deleted).toBe(true);
      expect(dbRow.is_active).toBe(false);
    });

    await test.step('Verify direct navigation to its Edit/View page no longer works', async () => {
      await page.goto('/staff/edit/' + staffId);
      await expect(page).toHaveURL(/\/staff\/$/);
      await expect(page.locator('.alert-danger', { hasText: 'Staff member not found' })).toBeVisible();

      await page.goto('/staff/view/' + staffId);
      await expect(page).toHaveURL(/\/staff\/$/);
      await expect(page.locator('.alert-danger', { hasText: 'Staff member not found' })).toBeVisible();
    });
  });
});
