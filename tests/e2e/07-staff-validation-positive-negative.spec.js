const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const path = require('path');
const { StaffPage } = require('./staff-page');

// Positive/negative coverage for this session's Staff form work:
// duplicate-name detection, strict phone validation (first-digit, repeated,
// sequential), the Address "State" dropdown, and all-required-fields-at-once
// validation. IDs use a NEW-STF- prefix, separate from the existing
// TC-/NEG- numbering, to avoid colliding with 01/04/06's ranges.

function dbGetByEmployeeId(employeeId) {
  const output = execFileSync(
    'python',
    [path.join(__dirname, 'db_helper.py'), 'get-by-employee-id', employeeId],
    { cwd: path.join(__dirname, '..', '..'), encoding: 'utf-8' }
  ).trim();
  return output === 'null' ? null : JSON.parse(output);
}

test.describe('Staff Form - Duplicate Name Detection', () => {
  const FIRST_NAME = 'PWTestFixtureDup' + Date.now();

  test('NEW-STF-001 (positive) - first Add with a unique name saves successfully', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    await staff.fillNewStaff({ firstName: FIRST_NAME, lastName: 'Original', position: 'Cleaning Staff' });
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/$/);
    await expect(staff.rowByText(FIRST_NAME)).toBeVisible();
  });

  test('NEW-STF-002 (negative) - Add with the same First+Last Name is blocked', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    await staff.firstNameInput.fill(FIRST_NAME);
    await staff.lastNameInput.fill('Original');
    // The blur-triggered client-side check surfaces the warning banner
    // before Save is even clicked - blur off Last Name to trigger it,
    // matching how a real user tabs through the form.
    await staff.lastNameInput.blur();
    await expect(page.locator('#duplicateNameWarning')).toBeVisible();
    await expect(page.locator('#duplicateNameWarning')).toContainText('A staff member with this name already exists.');

    // Filling out the rest and attempting Save must still be blocked -
    // the warning is a hard stop, not just advisory.
    await staff.positionSelect.selectOption({ label: 'Cleaning Staff' });
    await staff.phoneInput.fill('9000000005');
    await staff.departmentSelect.selectOption({ index: 1 });
    if (!(await staff.locationSelect.isDisabled())) await staff.locationSelect.selectOption({ index: 1 });
    await staff.bankAccountInput.fill('123456789012');
    await staff.ifscInput.fill('SBIN0005814');
    await staff.monthlySalaryInput.fill('25000');
    await staff.addressInput.fill('123 Test Street');
    await staff.cityInput.fill('Test City');
    await staff.zipInput.fill('500001');
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/add/);
  });

  test('NEW-STF-003 (positive) - a different name (same first, different last) is not treated as a duplicate', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    await staff.fillNewStaff({ firstName: FIRST_NAME, lastName: 'NotADuplicate', position: 'Cleaning Staff' });
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/$/);
    await expect(staff.rowByText('NotADuplicate')).toBeVisible();
  });

  test('NEW-STF-004 (positive) - editing a staff member and resubmitting their own unchanged name does not flag itself as a duplicate', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.goto();
    const row = staff.rowByText(FIRST_NAME).filter({ hasText: 'Original' });
    await staff.clickEdit(row);
    await expect(page.getByRole('heading', { name: 'Edit Staff Member' })).toBeVisible();
    // Re-submit without changing First/Last Name at all.
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/$/);
  });
});

test.describe('Staff Form - Phone Validation', () => {
  test('NEW-STF-005 (positive) - a valid 10-digit number starting 6-9 is accepted', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    await staff.fillNewStaff({ firstName: 'PWTestFixturePhoneValid' + Date.now(), phone: '7989189681', position: 'Cleaning Staff' });
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/$/);
  });

  const invalidPhoneCases = [
    { label: 'starts with 0', value: '0123456789' },
    { label: 'starts with 1 (sequential)', value: '1234567890' },
    { label: 'starts with 5', value: '5123456789' },
    { label: 'all repeated digits', value: '9999999999' },
    { label: 'descending sequential', value: '9876543210' },
  ];
  for (const { label, value } of invalidPhoneCases) {
    test(`NEW-STF-006 (negative) - phone ${label} (${value}) is rejected client-side`, async ({ page }) => {
      const staff = new StaffPage(page);
      await staff.gotoAdd();
      await staff.firstNameInput.fill('PWTestFixturePhoneInvalid' + Date.now());
      await staff.lastNameInput.fill('Fixture');
      await staff.positionSelect.selectOption({ label: 'Cleaning Staff' });
      await staff.phoneInput.fill(value);
      await staff.phoneInput.blur();
      await expect(staff.phoneInput).toHaveClass(/is-invalid/);
      await staff.submit();
      // Blocked client-side - never left the Add page.
      await expect(page).toHaveURL(/\/staff\/add/);
    });
  }

  test('NEW-STF-007 (negative) - an invalid phone reaching the server directly (client JS bypassed entirely) is still rejected', async ({ page, request }) => {
    // The Phone field has its own dedicated JS validator (independent of
    // the `pattern` HTML attribute) that runs on every submit, so removing
    // just `pattern`/`maxlength` (staff.bypassClientValidation) is not
    // enough to reach the server with a bad number - proving the server is
    // the real backstop means posting directly, simulating JS having never
    // run at all (disabled, blocked, or buggy).
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    // Reuse the logged-in browser's own session cookie for the direct POST.
    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find((c) => c.name === 'session');
    const response = await request.post('/staff/add', {
      headers: { Cookie: `session=${sessionCookie.value}` },
      form: {
        first_name: 'PWTestFixturePhoneSrv' + Date.now(),
        last_name: 'Fixture',
        phone: '1234567890', // sequential - invalid
        position_id: await staff.positionSelect.locator('option', { hasText: 'Cleaning Staff' }).getAttribute('value'),
        department_id: await staff.departmentSelect.locator('option').nth(1).getAttribute('value'),
        location_id: (await staff.locationSelect.locator('option').nth(1).getAttribute('value')) || '',
        bank_account_number: '123456789012',
        ifsc_code: 'SBIN0005814',
        monthly_salary: '25000',
        address: '123 Test Street',
        city: 'Test City',
        state: 'Andhra Pradesh',
        zip_code: '500001',
      },
    });
    expect(response.ok()).toBe(true); // the route itself renders 200 with the error flashed, not a 4xx
    const body = await response.text();
    expect(body).toContain('Enter a valid 10-digit mobile number');
  });
});

test.describe('Staff Form - Address "State" Dropdown', () => {
  test('NEW-STF-008 (positive) - State defaults to Andhra Pradesh on Add Staff Member', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    await expect(staff.stateInput).toHaveValue('Andhra Pradesh');
  });

  test('NEW-STF-009 (positive) - a different state can be selected and is saved', async ({ page }) => {
    const staff = new StaffPage(page);
    const firstName = 'PWTestFixtureState' + Date.now();
    await staff.gotoAdd();
    await staff.fillNewStaff({ firstName, position: 'Cleaning Staff', state: 'Kerala' });
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/$/);

    const row = staff.rowByText(firstName);
    await staff.clickEdit(row);
    await expect(staff.stateInput).toHaveValue('Kerala');
  });

  test('NEW-STF-010 (negative) - State is a fixed dropdown, not free text - an arbitrary string cannot be entered', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    // A <select> has no matching <option> for an arbitrary string -
    // selectOption keeps retrying until it times out, so a short explicit
    // timeout here just proves it never resolves, without waiting the
    // suite's full default timeout for what is an expected failure.
    await expect(staff.stateInput.selectOption({ label: 'Narnia' }, { timeout: 2000 })).rejects.toThrow();
    // The field's actual value is left completely untouched by the failed attempt.
    await expect(staff.stateInput).toHaveValue('Andhra Pradesh');
  });
});

test.describe('Staff Form - All Required Fields Validated At Once', () => {
  test('NEW-STF-011 (negative) - submitting a fully empty Add Staff form flags every required field simultaneously', async ({ page }) => {
    const staff = new StaffPage(page);
    await staff.gotoAdd();
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/add/);

    const requiredFieldIds = [
      'first_name', 'last_name', 'phone', 'position_id', 'department_id',
      'bank_account_number', 'ifsc_code', 'monthly_salary',
      'address', 'city', 'zip_code',
    ];
    for (const id of requiredFieldIds) {
      await expect(page.locator('#' + id)).toHaveClass(/is-invalid/);
    }
  });

  test('NEW-STF-012 (positive) - filling every required field clears its red state and allows submission', async ({ page }) => {
    const staff = new StaffPage(page);
    const firstName = 'PWTestFixtureAllFields' + Date.now();
    await staff.gotoAdd();

    // Trigger the all-empty validation pass first (mirrors a real user
    // clicking Save too early) and confirm the red state is live...
    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/add/);
    await expect(staff.firstNameInput).toHaveClass(/is-invalid/);

    // ...then fill in every required field and confirm it clears.
    await staff.fillNewStaff({ firstName, position: 'Cleaning Staff' });
    await expect(staff.firstNameInput).not.toHaveClass(/is-invalid/);
    await expect(staff.phoneInput).not.toHaveClass(/is-invalid/);

    await staff.submit();
    await expect(page).toHaveURL(/\/staff\/$/);
    await expect(staff.rowByText(firstName)).toBeVisible();
  });
});
