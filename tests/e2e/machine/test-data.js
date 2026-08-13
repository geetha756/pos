const settings = {
  off_temperature: 82,
  on_temperature: 74,
  temperature_offset: 0,
  buzzer_enabled: true,
};

const status = {
  is_online: true,
  machine_status: 'running',
  heater_status: 'on',
  sensor_status: 'ok',
  last_seen: '2026-08-13T06:00:00Z',
};

const temperatureLogs = {
  items: [{ temperature: 78.5, recorded_at: '2026-08-13T06:00:00Z' }],
  total: 1,
};

function success(data) { return { success: true, data }; }

module.exports = { settings, status, temperatureLogs, success };
