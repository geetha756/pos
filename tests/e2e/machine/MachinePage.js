const { success, settings, status, temperatureLogs } = require('./test-data');

// Locators and API fixtures for the actual Machine module.  The production
// page is a single-machine Idli monitor, not a machine CRUD list.
class MachinePage {
  constructor(page) { this.page = page; }

  async installConnectedService({ settingsResponse = success(settings), statusResponse = success(status), events = [], commands = [] } = {}) {
    await this.page.route('**/machines/idli/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().isNavigationRequest()) {
        const response = await route.fetch();
        const html = (await response.text()).replace('configured: false', 'configured: true');
        return route.fulfill({ response, body: html });
      }
      let body = success({});
      if (url.pathname.endsWith('/status')) body = statusResponse;
      else if (url.pathname.endsWith('/settings') && route.request().method() === 'GET') body = settingsResponse;
      else if (url.pathname.endsWith('/temperature-logs')) body = success(temperatureLogs);
      else if (url.pathname.endsWith('/events')) body = success({ items: events, total: events.length });
      else if (url.pathname.endsWith('/commands')) body = success({ items: commands, total: commands.length });
      else if (url.pathname.endsWith('/settings/sync')) body = success({ request_id: null });
      else if (url.pathname.endsWith('/settings') && route.request().method() === 'PATCH') body = success(settings);
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
  }

  async gotoDashboard() { await this.page.goto('/machines/idli'); }
  async gotoSettings() { await this.page.goto('/machines/idli/settings'); }
  async gotoHistory() { await this.page.goto('/machines/idli/history'); }
}

module.exports = { MachinePage };
