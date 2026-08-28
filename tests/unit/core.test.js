// Unit tests for pos/static/js/eidli/core.js — this file already exports
// its full public surface via window.Eidli, so no extraction hook is
// needed; loaded via the same harness for consistency with the other
// suites.
import { describe, it, expect, beforeAll } from 'vitest';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { loadEidliModules } = require('./loadEidliModule.js');

let Eidli;

beforeAll(() => {
  const { window } = loadEidliModules(['core.js']);
  Eidli = window.Eidli;
});

describe('fmtTemp — temperature formatting', () => {
  it('positive: formats a real number to one decimal with the degree symbol', () => {
    expect(Eidli.fmtTemp(78.456)).toBe('78.5°C');
  });
  it('boundary: exactly 0 is a valid real reading, not treated as missing', () => {
    expect(Eidli.fmtTemp(0)).toBe('0.0°C');
  });
  it('negative: null/undefined/empty-string/non-numeric all render the placeholder, never "NaN°C"', () => {
    expect(Eidli.fmtTemp(null)).toBe('—');
    expect(Eidli.fmtTemp(undefined)).toBe('—');
    expect(Eidli.fmtTemp('')).toBe('—');
    expect(Eidli.fmtTemp('not-a-number')).toBe('—');
  });
});

describe('istDateISO — IST calendar-date resolution (timezone-independent of the viewing device)', () => {
  it('positive: resolves the correct IST calendar date regardless of the moment being near a UTC day boundary', () => {
    // 2026-08-13 18:31 UTC = 2026-08-14 00:01 IST — already past midnight in India.
    expect(Eidli.istDateISO(new Date('2026-08-13T18:31:00Z'))).toBe('2026-08-14');
  });
  it('boundary: exactly IST midnight resolves to the new day, not the previous one', () => {
    expect(Eidli.istDateISO(new Date('2026-08-13T18:30:00Z'))).toBe('2026-08-14'); // 18:30 UTC = 00:00 IST
  });
});

describe('fmtRelative — relative "time ago" formatting', () => {
  it('positive: a few seconds ago reads "just now"', () => {
    expect(Eidli.fmtRelative(new Date(Date.now() - 2000).toISOString())).toBe('just now');
  });
  it('positive: minutes-ago and hours-ago format correctly', () => {
    expect(Eidli.fmtRelative(new Date(Date.now() - 5 * 60000).toISOString())).toBe('5m ago');
    expect(Eidli.fmtRelative(new Date(Date.now() - 3 * 3600000).toISOString())).toBe('3h ago');
  });
  it('boundary: more than 24h ago falls back to an absolute date+time, not an ever-growing "Nd ago"', () => {
    const iso = new Date(Date.now() - 2 * 86400000).toISOString();
    const result = Eidli.fmtRelative(iso);
    expect(result).not.toMatch(/ago/);
  });
  it('negative: null/empty/unparseable input renders the placeholder, never throws', () => {
    expect(Eidli.fmtRelative(null)).toBe('—');
    expect(Eidli.fmtRelative('')).toBe('—');
    expect(Eidli.fmtRelative('not-a-date')).toBe('—');
  });
});

describe('heaterBadge — heater ON/OFF/unknown state determination', () => {
  it('positive: "on" (case-insensitive) renders the ON badge', () => {
    expect(Eidli.heaterBadge('ON')).toContain('HEATER ON');
    expect(Eidli.heaterBadge('on')).toContain('HEATER ON');
  });
  it('positive: "off" renders the OFF badge', () => {
    expect(Eidli.heaterBadge('off')).toContain('HEATER OFF');
  });
  it('negative: null/empty/unrecognized status renders UNKNOWN, never a fabricated ON/OFF guess', () => {
    expect(Eidli.heaterBadge(null)).toContain('UNKNOWN');
    expect(Eidli.heaterBadge('')).toContain('UNKNOWN');
    expect(Eidli.heaterBadge('heating_up')).toContain('UNKNOWN');
  });
});

describe('sensorBadge — sensor connected/disconnected/error/unknown state', () => {
  it('positive: each real backend status maps to its correct badge', () => {
    expect(Eidli.sensorBadge('connected')).toContain('CONNECTED');
    expect(Eidli.sensorBadge('disconnected')).toContain('DISCONNECTED');
    expect(Eidli.sensorBadge('error')).toContain('FAULT');
  });
  it('negative: an unrecognized/null status is UNKNOWN, never silently mapped to a misleading "connected"', () => {
    expect(Eidli.sensorBadge(null)).toContain('UNKNOWN');
    expect(Eidli.sensorBadge('weird_new_status')).toContain('UNKNOWN');
  });
});

describe('machineStateBadge — machine ONLINE/OFFLINE/running/fault state determination', () => {
  it('positive: fault/offline map to the bad (red) badge class', () => {
    expect(Eidli.machineStateBadge('fault')).toContain('eidli-b-bad');
    expect(Eidli.machineStateBadge('offline')).toContain('eidli-b-bad');
  });
  it('positive: running/heating/cooking map to the good (green) badge class', () => {
    expect(Eidli.machineStateBadge('running')).toContain('eidli-b-good');
    expect(Eidli.machineStateBadge('heating')).toContain('eidli-b-good');
  });
  it('boundary: idle maps to neutral, not good or bad', () => {
    expect(Eidli.machineStateBadge('idle')).toContain('eidli-b-neutral');
  });
  it('negative: empty/null state renders UNKNOWN rather than defaulting to any specific real state', () => {
    expect(Eidli.machineStateBadge(null)).toContain('UNKNOWN');
    expect(Eidli.machineStateBadge('')).toContain('UNKNOWN');
  });
  it('negative: an entirely unrecognized state string is still shown (uppercased) as neutral, never dropped/hidden', () => {
    const result = Eidli.machineStateBadge('some_future_state');
    expect(result).toContain('SOME_FUTURE_STATE');
    expect(result).toContain('eidli-b-neutral');
  });
});

describe('esc — HTML-escaping (XSS-safety for any dynamic backend text rendered as innerHTML)', () => {
  it('positive: escapes all five dangerous characters', () => {
    expect(Eidli.esc('<script>alert("x")&\'</script>')).toBe('&lt;script&gt;alert(&quot;x&quot;)&amp;&#39;&lt;/script&gt;');
  });
  it('boundary: null/undefined become an empty string, never the literal text "null"/"undefined"', () => {
    expect(Eidli.esc(null)).toBe('');
    expect(Eidli.esc(undefined)).toBe('');
  });
});
