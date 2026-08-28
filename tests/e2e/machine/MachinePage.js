const { success, settings, status, temperatureLogs } = require('./test-data');

// Locators and API fixtures for the actual Machine module.  The production
// page is a single-machine Idli monitor, not a machine CRUD list.
class MachinePage {
  constructor(page) { this.page = page; }

  async installConnectedService({
    settingsResponse = success(settings), statusResponse = success(status),
    events = [], commands = [], heatingCycles = [], temperatureLogsResponse = null,
    eventsResponse = null, commandsResponse = null, heatingCyclesResponse = null,
  } = {}) {
    await this.page.route('**/machines/idli/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().isNavigationRequest()) {
        const response = await route.fetch();
        const html = (await response.text()).replace('configured: false', 'configured: true');
        return route.fulfill({ response, body: html });
      }
      let body = success({});
      let status_ = 200;
      if (url.pathname.endsWith('/status')) body = statusResponse;
      else if (url.pathname.endsWith('/settings') && route.request().method() === 'GET') body = settingsResponse;
      else if (url.pathname.endsWith('/temperature-logs')) body = temperatureLogsResponse || success(temperatureLogs);
      else if (url.pathname.endsWith('/events')) body = eventsResponse || success({ items: events, total: events.length });
      else if (url.pathname.endsWith('/commands')) body = commandsResponse || success({ items: commands, total: commands.length });
      else if (url.pathname.endsWith('/heating-cycles')) body = heatingCyclesResponse || success({ items: heatingCycles, total: heatingCycles.length });
      else if (url.pathname.endsWith('/settings/sync')) body = success({ request_id: null });
      else if (url.pathname.endsWith('/settings') && route.request().method() === 'PATCH') body = success(settings);
      if (typeof body === 'object' && body !== null && typeof body.__status === 'number') { status_ = body.__status; }
      await route.fulfill({ status: status_, contentType: 'application/json', body: JSON.stringify(body) });
    });
  }

  async gotoDashboard() { await this.page.goto('/machines/idli'); }
  async gotoSettings() { await this.page.goto('/machines/idli/settings'); }
  async gotoHistory() { await this.page.goto('/machines/idli/history'); }
}

module.exports = { MachinePage };
