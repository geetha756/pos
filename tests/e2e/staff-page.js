// Reusable locators + actions for the Staff Management module.
// Centralizes every selector here so spec files describe *behavior*, not
// DOM structure - if the markup changes, only this file needs updating.
class StaffPage {
  constructor(page) {
    this.page = page;
    this.table = page.locator('#staffTable');
    this.rows = page.locator('#staffTable tbody tr');
    this.statusFilter = page.locator('#statusFilter');
    this.locationFilter = page.locator('#locationFilter');
    this.searchInput = page.locator('#searchInput');
    this.deactivateModal = page.locator('#deactivateModal');
    this.deleteModal = page.locator('#deleteModal');
  }

  async goto(query = '') {
    await this.page.goto('/staff/' + query);
  }

  async gotoAdd() {
    await this.page.goto('/staff/add');
  }

  rowByText(text) {
    return this.rows.filter({ hasText: text });
  }

  visibleRows() {
    return this.page.locator('#staffTable tbody tr:visible');
  }

  statusCell(row) {
    return row.locator('td').nth(5);
  }

  locationCell(row) {
    return row.locator('td').nth(4);
  }

  employeeIdCell(row) {
    return row.locator('td').first();
  }

  async selectStatus(value) {
    await this.statusFilter.selectOption(value);
  }

  // After a click-driven redirect (POST -> 302 -> GET, e.g. a form submit
  // or the Deactivate/Activate actions), Playwright's auto-waiting and
  // `expect(page).toHaveURL()` only guarantee the URL changed - not that
  // the destination page's own inline <script> (which attaches the Staff
  // Status <select>'s 'change' listener, near the bottom of the body) has
  // finished executing yet. Call this before interacting with any control
  // that depends on that script, right after such a redirect.
  async waitForScriptsReady() {
    await this.page.waitForLoadState('load');
  }

  async search(text) {
    await this.searchInput.fill(text);
  }

  async filterByLocation(value) {
    await this.locationFilter.selectOption(value);
  }

  async clickView(row) {
    await row.getByRole('link', { name: 'View' }).click();
  }

  async clickEdit(row) {
    await row.getByRole('link', { name: 'Edit' }).click();
  }

  async openDeactivateModal(row) {
    await row.locator('.deactivate-staff-btn').click();
    await this.deactivateModal.waitFor({ state: 'visible' });
  }

  async confirmDeactivate() {
    await this.deactivateModal.getByRole('button', { name: 'Deactivate', exact: true }).click();
  }

  async deactivate(row) {
    await this.openDeactivateModal(row);
    await this.confirmDeactivate();
  }

  async activate(row) {
    await row.getByRole('button', { name: 'Activate' }).click();
  }

  async openDeleteModal(row) {
    await row.locator('.delete-staff-btn').click();
    await this.deleteModal.waitFor({ state: 'visible' });
  }

  async confirmDelete() {
    await this.deleteModal.getByRole('button', { name: 'Delete', exact: true }).click();
  }

  async delete(row) {
    await this.openDeleteModal(row);
    await this.confirmDelete();
  }

  // --- Add / Edit form (shared field ids between add.html and edit.html) ---
  get firstNameInput() { return this.page.locator('#first_name'); }
  get lastNameInput() { return this.page.locator('#last_name'); }
  get phoneInput() { return this.page.locator('#phone'); }
  get positionSelect() { return this.page.locator('#position_id'); }
  get hireDateInput() { return this.page.locator('#hire_date'); }
  get bankAccountInput() { return this.page.locator('#bank_account_number'); }
  get ifscInput() { return this.page.locator('#ifsc_code'); }
  get monthlySalaryInput() { return this.page.locator('#monthly_salary'); }
  get notesInput() { return this.page.locator('#notes'); }
  get submitButton() { return this.page.locator('button[form="staffForm"]'); }
  get phoneInvalidFeedback() {
    return this.page.locator('#staffForm div.invalid-feedback', { hasText: 'Phone number must be exactly 10 digits.' });
  }
  get bankAccountInvalidFeedback() {
    return this.page.locator('#staffForm div.invalid-feedback', { hasText: 'Bank Account Number must be 5-20 digits.' });
  }
  get ifscInvalidFeedback() {
    return this.page.locator('#staffForm div.invalid-feedback', { hasText: 'Please enter a valid IFSC code.' });
  }

  // Last Name and Phone are required fields server- and client-side, so
  // every caller gets a valid default for both unless it deliberately wants
  // to test the blank/invalid case itself (see NEG-008/NEG-009).
  async fillNewStaff({ firstName, lastName = 'Fixture', phone = '9000000000', position }) {
    await this.firstNameInput.fill(firstName);
    await this.lastNameInput.fill(lastName);
    if (phone) await this.phoneInput.fill(phone);
    if (position) await this.positionSelect.selectOption({ label: position });
  }

  async submit() {
    await this.submitButton.click();
  }

  // Removes the given HTML5 constraint attributes from a field so a submit
  // reaches the server unfiltered - used only to prove the server enforces
  // the same rule independently of the browser (defense in depth), never
  // to work around anything in the app itself.
  async bypassClientValidation(locator, attributes) {
    await locator.evaluate((el, attrs) => attrs.forEach((a) => el.removeAttribute(a)), attributes);
  }
}

module.exports = { StaffPage };
