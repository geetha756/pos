const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    storageState: './tests/e2e/.auth/admin-state.json',
    viewport: { width: 1280, height: 900 },
  });
  const page = await context.newPage();

  await page.goto('http://localhost:5000/machines/idli', { waitUntil: 'networkidle', timeout: 15000 }).catch(e => console.log('nav1 err', e.message));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: 'shot-dashboard.png', fullPage: true });
  console.log('dashboard shot saved, url=', page.url());

  await page.goto('http://localhost:5000/machines/idli/history', { waitUntil: 'networkidle', timeout: 15000 }).catch(e => console.log('nav2 err', e.message));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: 'shot-history.png', fullPage: true });
  console.log('history shot saved, url=', page.url());

  await browser.close();
})();
