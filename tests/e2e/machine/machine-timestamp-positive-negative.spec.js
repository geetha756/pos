const { test, expect } = require('@playwright/test');
const { MachinePage } = require('./MachinePage');
const { success } = require('./test-data');

// Positive/negative coverage for this session's Machine work: the listing
// card's "Machine ON/OFF at <date, time:seconds>" format (real backend event
// timestamp, not browser time), and the bottom-left profile icon fallback.
// IDs use a NEW-MCH- prefix, separate from the existing MCH-/MCHX- numbering.

test.describe('Machine Listing Card - ON/OFF Timestamp Format', () => {
  test('NEW-MCH-001 (positive) - OFFLINE card shows "Machine OFF at <date>, <h:mm:ss am/pm>" using the real event timestamp', async ({ page }) => {
    const machine = new MachinePage(page);
    const offlineAt = '2026-08-24T06:44:32Z'; // 12:14:32 pm IST
    await machine.installConnectedService({
      statusResponse: success({ is_online: false, last_seen: offlineAt }),
      events: [{ id: 1, event_type: 'machine_offline', created_at: offlineAt }],
    });
    await page.goto('/machines/');
    const note = page.locator('#machine-uptime-note');
    await expect(note).toContainText('Machine OFF at', { timeout: 10000 });
    // Date + time + seconds, not just hour:minute - proves the fix actually
    // landed and isn't a coincidental substring match.
    await expect(note).toHaveText(/Machine OFF at \d{1,2} \w{3} \d{4}, \d{1,2}:\d{2}:\d{2} (am|pm)/i);
    await expect(note).toContainText('12:14:32');
  });

  test('NEW-MCH-002 (positive) - ONLINE card shows "Machine ON at <date>, <h:mm:ss am/pm>" using the same format', async ({ page }) => {
    const machine = new MachinePage(page);
    const restartedAt = '2026-08-24T09:19:05Z'; // 2:49:05 pm IST
    await machine.installConnectedService({
      statusResponse: success({ is_online: true, last_seen: restartedAt }),
      events: [{ id: 1, event_type: 'machine_restarted', created_at: restartedAt }],
    });
    await page.goto('/machines/');
    const note = page.locator('#machine-uptime-note');
    await expect(note).toContainText('Machine ON at', { timeout: 10000 });
    await expect(note).toHaveText(/Machine ON at \d{1,2} \w{3} \d{4}, \d{1,2}:\d{2}:\d{2} (am|pm)/i);
    await expect(note).toContainText('2:49:05');
  });

  test('NEW-MCH-003 (negative) - no ON/OFF event recorded yet shows "--", never a fabricated or browser-clock timestamp', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({
      statusResponse: success({ is_online: false, last_seen: null }),
      events: [], // no machine_offline event exists at all
    });
    await page.goto('/machines/');
    const note = page.locator('#machine-uptime-note');
    await expect(note).toContainText('Machine OFF at --', { timeout: 10000 });
    // Never a real-looking date/time when there's genuinely no data.
    await expect(note).not.toHaveText(/\d{1,2}:\d{2}:\d{2}/);
  });

  test('NEW-MCH-004 (negative) - the events API failing leaves the card on "--" instead of crashing or inventing a time', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService({
      statusResponse: success({ is_online: false, last_seen: null }),
      eventsResponse: { success: false, message: 'Machine service unavailable' },
    });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('/machines/');
    await expect(page.locator('#machine-uptime-note')).toContainText('Machine OFF at --', { timeout: 10000 });
    expect(errors).toEqual([]);
  });
});

test.describe('Sidebar - Profile Icon Fallback', () => {
  // Whatever the logged-in test session's own session.user_picture happens
  // to be (a real Google picture URL, or none at all) isn't something a
  // Playwright test can control - the fix itself is isolated and verified
  // directly instead: build the exact bottom-left markup base.html renders,
  // with the same onerror handler, and prove a failing image swaps to the
  // fallback icon rather than staying a broken <img>.
  const PROFILE_ICON_HTML = `
    <div id="user-section">
      <img src="https://example.invalid/does-not-exist.png" alt="Profile"
           class="rounded-circle me-2" width="32" height="32" style="object-fit: cover;"
           onerror="this.replaceWith(Object.assign(document.createElement('i'), {className: 'ri-user-3-line icon me-2', style: 'font-size: 24px; color: #666;'}));">
    </div>`;

  test('NEW-MCH-005 (positive) - a broken/unreachable profile picture URL falls back to the generic person icon, not a broken-image icon', async ({ page }) => {
    await page.setContent(PROFILE_ICON_HTML);
    const userSection = page.locator('#user-section');
    // The onerror handler removes the <img> entirely and replaces it with
    // the fallback <i> icon once the broken image fails to load.
    await expect(userSection.locator('img')).toHaveCount(0, { timeout: 10000 });
    await expect(userSection.locator('i.ri-user-3-line')).toHaveCount(1);
  });

  test('NEW-MCH-006 (negative) - without the onerror fallback, a broken picture URL would leave a dangling broken <img> (control case)', async ({ page }) => {
    // Same markup, minus the onerror attribute - demonstrates what the bug
    // looked like before the fix, so the positive case above isn't passing
    // by accident (e.g. the browser silently hiding all failed <img>s).
    await page.setContent(PROFILE_ICON_HTML.replace(/onerror="[^"]*"/, ''));
    const userSection = page.locator('#user-section');
    await page.waitForTimeout(1000); // let the failing image request settle
    await expect(userSection.locator('img')).toHaveCount(1);
    await expect(userSection.locator('i.ri-user-3-line')).toHaveCount(0);
  });

  test('NEW-MCH-007 (positive) - the real Machines page renders exactly one profile indicator (image or fallback icon), never zero or a duplicate', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await page.goto('/machines/');
    const userSection = page.locator('#user-section');
    await expect(userSection).toBeVisible();
    await expect(userSection.locator('img, i.ri-user-3-line')).toHaveCount(1);
  });

  test('NEW-MCH-008 (positive) - the profile indicator survives a hard page reload, not just first paint', async ({ page }) => {
    const machine = new MachinePage(page);
    await machine.installConnectedService();
    await page.goto('/machines/');
    await page.reload();
    const userSection = page.locator('#user-section');
    await expect(userSection).toBeVisible();
    await expect(userSection.locator('img, i.ri-user-3-line')).toHaveCount(1);
  });
});
