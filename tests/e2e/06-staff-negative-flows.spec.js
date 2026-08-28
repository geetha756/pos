const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const path = require('path');
const { StaffPage } = require('./staff-page');

function dbGetByEmployeeId(employeeId) {
  const output = execFileSync(
    'python',
    [path.join(__dirname, 'db_helper.py'), 'get-by-employee-id', employeeId],
    { cwd: path.join(__dirname, '..', '..'), encoding: 'utf-8' }
  ).trim();
  return output === 'null' ? null : JSON.parse(output);
}

function dbLinkManager(staffEmployeeId, managerEmployeeId) {
  const output = execFileSync(
    'python',
    [path.join(__dirname, 'db_helper.py'), 'link-manager', staffEmployeeId, managerEmployeeId],
    { cwd: path.join(__dirname, '..', '..'), encoding: 'utf-8' }
  ).trim();
  return JSON.parse(output);
}

test.describe('Staff Management - Negative Flows (standalone)', () => {
  test('NEG-001: Add Staff Member is blocked when required First Name is empty', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Add Staff Member, leave First Name empty, fill Position, submit', async () => {
      await staff.gotoAdd();
      await staff.positionSelect.selectOption({ label: 'Cleaning Staff' });
      await staff.submit();
    });

    await test.step('Verify submission was blocked and no record was created', async () => {
      await expect(page).toHaveURL(/\/staff\/add/);
      await expect(page.locator('#first_name:invalid')).toHaveCount(1);
    });
  });

  test('NEG-002: Add Staff Member is blocked when required Position is not selected', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Add Staff Member, fill First Name, leave Position unselected, submit', async () => {
      await staff.gotoAdd();
      await staff.firstNameInput.fill('PWTestNegativeNoPosition');
      await staff.submit();
    });

    await test.step('Verify submission was blocked and no record was created', async () => {
      await expect(page).toHaveURL(/\/staff\/add/);
      await expect(page.locator('#position_id:invalid')).toHaveCount(1);
      await staff.goto();
      await expect(staff.rowByText('PWTestNegativeNoPosition')).toHaveCount(0);
    });
  });

  test('NEG-008: Add Staff Member is blocked when required Last Name is empty', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Add Staff Member, fill First Name/Phone/Position, leave Last Name empty, submit', async () => {
      await staff.gotoAdd();
      await staff.firstNameInput.fill('PWTestNegativeNoLastName');
      await staff.phoneInput.fill('9000000002');
      await staff.positionSelect.selectOption({ label: 'Cleaning Staff' });
      await staff.submit();
    });

    await test.step('Verify submission was blocked and no record was created', async () => {
      await expect(page).toHaveURL(/\/staff\/add/);
      await expect(page.locator('#last_name:invalid')).toHaveCount(1);
      await staff.goto();
      await expect(staff.rowByText('PWTestNegativeNoLastName')).toHaveCount(0);
    });
  });

  test('NEG-009: Add Staff Member is blocked when required Phone is empty', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Add Staff Member, fill First Name/Last Name/Position, leave Phone empty, submit', async () => {
      await staff.gotoAdd();
      await staff.firstNameInput.fill('PWTestNegativeNoPhone');
      await staff.lastNameInput.fill('Fixture');
      await staff.positionSelect.selectOption({ label: 'Cleaning Staff' });
      await staff.submit();
    });

    await test.step('Verify submission was blocked and no record was created', async () => {
      await expect(page).toHaveURL(/\/staff\/add/);
      await expect(page.locator('#phone:invalid')).toHaveCount(1);
      await staff.goto();
      await expect(staff.rowByText('PWTestNegativeNoPhone')).toHaveCount(0);
    });
  });

  test('NEG-012: Viewing a non-existent staff ID redirects with "not found"', async ({ page }) => {
    await test.step('Navigate directly to /staff/view/<a syntactically valid but nonexistent id>', async () => {
      await page.goto('/staff/view/00000000-0000-0000-0000-000000000000');
    });

    await test.step('Verify redirected back to the staff list with a not-found error', async () => {
      await expect(page).toHaveURL(/\/staff\/$/);
      await expect(page.locator('.alert-danger', { hasText: 'Staff member not found' })).toBeVisible();
    });
  });

  test('NEG-013: Editing a non-existent staff ID redirects with "not found"', async ({ page }) => {
    await test.step('Navigate directly to /staff/edit/<a syntactically valid but nonexistent id>', async () => {
      await page.goto('/staff/edit/00000000-0000-0000-0000-000000000000');
    });

    await test.step('Verify redirected back to the staff list with a not-found error', async () => {
      await expect(page).toHaveURL(/\/staff\/$/);
      await expect(page.locator('.alert-danger', { hasText: 'Staff member not found' })).toBeVisible();
    });
  });

  test('NEG-007: Unauthenticated access to Staff Management redirects to login', async ({ browser }) => {
    // Deliberately NOT using the shared admin storageState - a brand new
    // context with `storageState: undefined` explicitly overrides the
    // project-level `use.storageState` (playwright.config.js), which
    // `browser.newContext()` with no options otherwise still inherits.
    // Without this override the "fresh" context comes pre-loaded with the
    // admin session cookie, defeating the entire point of this test.
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    await test.step('Navigate directly to /staff/ with no session', async () => {
      await page.goto('/staff/');
    });

    await test.step('Verify redirected to the login page instead of the staff list', async () => {
      await expect(page).toHaveURL(/\/login/);
      await expect(page.locator('#staffTable')).toHaveCount(0);
    });

    await context.close();
  });

  test('NEG-014: Unauthenticated access to Add/View/Edit staff routes also redirects to login', async ({ browser }) => {
    const context = await browser.newContext({ storageState: undefined });
    const page = await context.newPage();

    for (const path of ['/staff/add', '/staff/view/00000000-0000-0000-0000-000000000000', '/staff/edit/00000000-0000-0000-0000-000000000000']) {
      await test.step(`Navigate directly to ${path} with no session`, async () => {
        await page.goto(path);
        await expect(page).toHaveURL(/\/login/);
      });
    }

    await context.close();
  });
});

test.describe.serial('Staff Management - Negative Flows (server-side validation & business rules)', () => {
  const MANAGER_FIRST_NAME = 'PWTestFixtureMgr' + Date.now();
  const SUB_FIRST_NAME = 'PWTestFixtureSub' + Date.now();
  let managerEmployeeId, subEmployeeId;

  test('Setup: create a manager fixture and a subordinate linked to it', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Create the manager fixture', async () => {
      await staff.gotoAdd();
      await staff.fillNewStaff({ firstName: MANAGER_FIRST_NAME, position: 'Cleaning Staff' });
      await staff.submit();
      await expect(page).toHaveURL(/\/staff\/$/);
      const row = staff.rowByText(MANAGER_FIRST_NAME);
      await expect(row).toBeVisible();
      managerEmployeeId = (await staff.employeeIdCell(row).textContent()).trim();
    });

    await test.step('Create the subordinate fixture', async () => {
      await staff.gotoAdd();
      await staff.fillNewStaff({ firstName: SUB_FIRST_NAME, position: 'Cleaning Staff' });
      await staff.submit();
      await expect(page).toHaveURL(/\/staff\/$/);
      const row = staff.rowByText(SUB_FIRST_NAME);
      await expect(row).toBeVisible();
      subEmployeeId = (await staff.employeeIdCell(row).textContent()).trim();
    });

    await test.step('Link the subordinate to the manager directly in the database (Add/Edit Staff Member has no Manager field)', async () => {
      const result = dbLinkManager(subEmployeeId, managerEmployeeId);
      expect(result.linked).toBe(true);
    });
  });

  test('NEG-003: Invalid Bank Account Number is rejected server-side', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Edit for the manager fixture', async () => {
      await staff.goto();
      const row = staff.rowByText(MANAGER_FIRST_NAME);
      await staff.clickEdit(row);
      await staff.waitForScriptsReady();
    });

    await test.step('Remove the client-side pattern constraint and submit an invalid value', async () => {
      // IFSC Code and Monthly Salary are also required on Edit now - give
      // them valid values so only Bank Account Number's invalid value is
      // under test (otherwise the browser's own required-field validation
      // on the other two would block the submit before it ever reaches
      // the server).
      await staff.ifscInput.fill('SBIN0005814');
      await staff.monthlySalaryInput.fill('25000');
      await staff.bypassClientValidation(staff.bankAccountInput, ['pattern']);
      await staff.bankAccountInput.fill('AB12');
      await staff.submit();
    });

    await test.step('Verify the server rejected it with the expected error and did not save it', async () => {
      await expect(page.locator('.alert-danger', { hasText: 'Bank Account Number must be 5-20 digits.' })).toBeVisible();
      const dbRow = dbGetByEmployeeId(managerEmployeeId);
      expect(dbRow.bank_account_number).not.toBe('AB12');
    });
  });

  test('NEG-004: Invalid IFSC Code is rejected server-side', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Edit for the manager fixture', async () => {
      await staff.goto();
      const row = staff.rowByText(MANAGER_FIRST_NAME);
      await staff.clickEdit(row);
      await staff.waitForScriptsReady();
    });

    await test.step('Remove the client-side pattern constraint and submit an invalid value', async () => {
      // Bank Account Number and Monthly Salary are also required on Edit
      // now - give them valid values so only IFSC Code's invalid value is
      // under test.
      await staff.bankAccountInput.fill('123456789012');
      await staff.monthlySalaryInput.fill('25000');
      await staff.bypassClientValidation(staff.ifscInput, ['pattern']);
      await staff.ifscInput.fill('12345');
      await staff.submit();
    });

    await test.step('Verify the server rejected it with the expected error and did not save it', async () => {
      await expect(page.locator('.alert-danger', { hasText: 'IFSC Code must be in a valid format' })).toBeVisible();
      const dbRow = dbGetByEmployeeId(managerEmployeeId);
      expect(dbRow.ifsc_code).not.toBe('12345');
    });
  });

  test('NEG-005: Negative Monthly Salary is rejected server-side', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Edit for the manager fixture', async () => {
      await staff.goto();
      const row = staff.rowByText(MANAGER_FIRST_NAME);
      await staff.clickEdit(row);
      await staff.waitForScriptsReady();
    });

    await test.step('Remove the client-side min constraint and submit a negative value', async () => {
      // Bank Account Number and IFSC Code are also required on Edit now -
      // give them valid values so only Monthly Salary's negative value is
      // under test.
      await staff.bankAccountInput.fill('123456789012');
      await staff.ifscInput.fill('SBIN0005814');
      await staff.bypassClientValidation(staff.monthlySalaryInput, ['min']);
      await staff.monthlySalaryInput.fill('-500');
      await staff.submit();
    });

    await test.step('Verify the server rejected it with the expected error and did not save it', async () => {
      await expect(page.locator('.alert-danger', { hasText: 'Monthly Salary cannot be negative.' })).toBeVisible();
      const dbRow = dbGetByEmployeeId(managerEmployeeId);
      expect(dbRow.monthly_salary).not.toBe('-500.00');
    });
  });

  test('NEG-011: Edit Staff Member is blocked when Bank Account Number is left blank', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Open Edit for the manager fixture', async () => {
      await staff.goto();
      const row = staff.rowByText(MANAGER_FIRST_NAME);
      await staff.clickEdit(row);
      await staff.waitForScriptsReady();
    });

    await test.step('Fill IFSC Code and a distinctive Monthly Salary, leave Bank Account Number blank, and submit', async () => {
      // Edit pre-populates this field with the existing value, so it must
      // be explicitly cleared to actually exercise the "left blank" case.
      await staff.bankAccountInput.fill('');
      await staff.ifscInput.fill('SBIN0005814');
      // Deliberately different from the fixture's default (25000) so the
      // "nothing was saved" check below can't pass by coincidence.
      await staff.monthlySalaryInput.fill('31000');
      await staff.submit();
    });

    await test.step('Verify submission was blocked and nothing was saved', async () => {
      await expect(page).toHaveURL(/\/staff\/edit\//);
      await expect(page.locator('#bank_account_number:invalid')).toHaveCount(1);
      const dbRow = dbGetByEmployeeId(managerEmployeeId);
      expect(dbRow.monthly_salary).not.toBe('31000.00');
    });
  });

  test('NEG-006: Deactivating a staff member who has subordinates succeeds and reassigns them', async ({ page }) => {
    const staff = new StaffPage(page);

    await test.step('Deactivate the manager fixture', async () => {
      await staff.goto();
      const row = staff.rowByText(MANAGER_FIRST_NAME);
      await staff.deactivate(row);
    });

    await test.step('Verify the success message and that the manager moved to Inactive', async () => {
      await expect(page.locator('.alert-success', { hasText: 'Staff member deactivated successfully!' })).toBeVisible();

      const row = staff.rowByText(MANAGER_FIRST_NAME);
      await expect(row).toHaveCount(0);

      const dbRow = dbGetByEmployeeId(managerEmployeeId);
      expect(dbRow.is_active).toBe(false);
    });

    await test.step('Verify the subordinate was automatically reassigned (to the manager\'s own manager, i.e. unmanaged here) rather than left pointing at a deactivated manager', async () => {
      const subRow = dbGetByEmployeeId(subEmployeeId);
      expect(subRow.manager_id).toBeNull();
    });
  });

  test('NEG-010: Deleting a staff member who has subordinates soft-deletes them and reassigns the subordinate', async ({ page }) => {
    const staff = new StaffPage(page);
    const deleteManagerName = 'PWTestFixtureDelMgr' + Date.now();
    const deleteSubName = 'PWTestFixtureDelSub' + Date.now();
    let deleteManagerEmployeeId, deleteSubEmployeeId;

    await test.step('Create a manager fixture and a subordinate linked to it', async () => {
      await staff.gotoAdd();
      await staff.fillNewStaff({ firstName: deleteManagerName, position: 'Cleaning Staff' });
      await staff.submit();
      let row = staff.rowByText(deleteManagerName);
      await expect(row).toBeVisible();
      deleteManagerEmployeeId = (await staff.employeeIdCell(row).textContent()).trim();

      await staff.gotoAdd();
      await staff.fillNewStaff({ firstName: deleteSubName, position: 'Cleaning Staff' });
      await staff.submit();
      row = staff.rowByText(deleteSubName);
      await expect(row).toBeVisible();
      deleteSubEmployeeId = (await staff.employeeIdCell(row).textContent()).trim();

      const result = dbLinkManager(deleteSubEmployeeId, deleteManagerEmployeeId);
      expect(result.linked).toBe(true);
    });

    await test.step('Delete the manager fixture', async () => {
      await staff.goto();
      const row = staff.rowByText(deleteManagerName);
      await staff.delete(row);
      await expect(page.locator('.alert-success', { hasText: 'Staff member deleted successfully!' })).toBeVisible();
      await expect(staff.rowByText(deleteManagerName)).toHaveCount(0);
    });

    await test.step('Verify the manager is soft-deleted, not removed', async () => {
      const dbRow = dbGetByEmployeeId(deleteManagerEmployeeId);
      expect(dbRow).not.toBeNull();
      expect(dbRow.is_deleted).toBe(true);
      expect(dbRow.is_active).toBe(false);
    });

    await test.step('Verify the subordinate was automatically reassigned rather than left pointing at a deleted manager', async () => {
      const subRow = dbGetByEmployeeId(deleteSubEmployeeId);
      expect(subRow.manager_id).toBeNull();
    });
  });
});
