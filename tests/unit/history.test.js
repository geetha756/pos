// Unit tests for pos/static/js/eidli/history.js's validateDateRange — the
// client-side From/To range validation logic.
import { describe, it, expect, beforeAll } from 'vitest';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { loadEidliModules } = require('./loadEidliModule.js');

let mod;

beforeAll(() => {
  const { hooks } = loadEidliModules(['core.js', 'history.js']);
  mod = hooks['history.js'];
});

describe('validateDateRange — From/To date+time validation (never reaches the network when invalid)', () => {
  it('positive: a valid From < To date range returns null (no error)', () => {
    expect(mod.validateDateRange('2026-08-01', '2026-08-07', '00:00', '23:59')).toBeNull();
  });
  it('negative: From date AFTER To date returns an error, blocking the request', () => {
    const err = mod.validateDateRange('2026-08-10', '2026-08-05', '00:00', '23:59');
    expect(err).toMatch(/From date cannot be after the To date/i);
  });
  it('boundary: From date === To date (same day) with From time <= To time is valid', () => {
    expect(mod.validateDateRange('2026-08-13', '2026-08-13', '00:00', '23:59')).toBeNull();
  });
  it('negative: From date === To date but From time > To time on that same day is invalid', () => {
    const err = mod.validateDateRange('2026-08-13', '2026-08-13', '18:00', '06:00');
    expect(err).toMatch(/From time cannot be after the To time/i);
  });
  it('boundary: same start/end time on the same day (identical From/To time) is valid — not treated as an error', () => {
    expect(mod.validateDateRange('2026-08-13', '2026-08-13', '12:00', '12:00')).toBeNull();
  });
  it('boundary: only From set (To empty) is valid — an unset side means "no bound on that side", not an error', () => {
    expect(mod.validateDateRange('2026-08-01', '', '00:00', '23:59')).toBeNull();
    expect(mod.validateDateRange('2026-08-01', null, '00:00', '23:59')).toBeNull();
  });
  it('boundary: only To set (From empty) is valid for the same reason', () => {
    expect(mod.validateDateRange('', '2026-08-07', '00:00', '23:59')).toBeNull();
  });
  it('boundary: both From and To empty is valid (no range at all — the "Clear" state)', () => {
    expect(mod.validateDateRange('', '', '00:00', '23:59')).toBeNull();
    expect(mod.validateDateRange(null, null, null, null)).toBeNull();
  });
  it('negative: From date after To date is caught even when times are both empty/defaulted', () => {
    const err = mod.validateDateRange('2026-08-10', '2026-08-05', '', '');
    expect(err).toMatch(/From date cannot be after the To date/i);
  });
});
