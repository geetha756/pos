// Unit tests for pos/static/js/eidli/history-analytics.js's pure/private
// logic, extracted from the REAL, unmodified production file via
// loadEidliModule.js (see that file's own header for the exact mechanism).
// No production file is changed to make these tests possible or pass.
import { describe, it, expect, beforeAll } from 'vitest';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { loadEidliModules } = require('./loadEidliModule.js');

let mod;

beforeAll(() => {
  const { hooks } = loadEidliModules(['core.js', 'history-analytics.js']);
  mod = hooks['history-analytics.js'];
});

function ist(iso) { return new Date(iso).getTime(); }

describe('fmtDurationHM — duration formatting (hours+minutes, no seconds)', () => {
  it('positive: formats an exact hour+minute value', () => {
    expect(mod.fmtDurationHM(3900)).toBe('1h 05m'); // 65 minutes
  });
  it('positive: formats a sub-hour value as minutes only', () => {
    expect(mod.fmtDurationHM(2700)).toBe('45m');
  });
  it('positive: the exact spec example — 5h 04m for 10:10 AM -> 3:14 PM (18240s)', () => {
    expect(mod.fmtDurationHM(18240)).toBe('5h 04m');
  });
  it('boundary: exactly 0 seconds', () => {
    expect(mod.fmtDurationHM(0)).toBe('0m');
  });
  it('boundary: sub-minute positive duration shows "<1m", never "0m" (never hides a real short cycle as nothing) — 30s rounds UP to 1m by design (Math.round(30/60)=1), so the true "<1m" boundary is under 30s', () => {
    expect(mod.fmtDurationHM(29)).toBe('<1m');
    expect(mod.fmtDurationHM(30)).toBe('1m'); // documents the real rounding behavior at the exact half-minute boundary
  });
  it('boundary: exact whole hour shows "00m" not "0m" for consistent width', () => {
    expect(mod.fmtDurationHM(7200)).toBe('2h 00m');
  });
  it('negative: negative seconds clamped to non-negative, never shown as a negative duration', () => {
    expect(mod.fmtDurationHM(-100)).toBe('0m');
  });
  it('negative: null/undefined/NaN all render the placeholder, never throw or show "NaN"', () => {
    expect(mod.fmtDurationHM(null)).toBe('—');
    expect(mod.fmtDurationHM(undefined)).toBe('—');
    expect(mod.fmtDurationHM(NaN)).toBe('—');
  });
});

describe('splitSpanByDay — IST day-boundary splitting (the midnight-crossing regression guard)', () => {
  it('positive: a span entirely within one IST day returns exactly one unmodified segment', () => {
    const segs = mod.splitSpanByDay(ist('2026-08-13T10:10:00+05:30'), ist('2026-08-13T15:14:00+05:30'));
    expect(segs.length).toBe(1);
    expect(segs[0].dayKey).toBe('2026-08-13');
    expect(Math.round(segs[0].seconds)).toBe(18240);
  });
  it('positive: THE spec regression — ON 10:10 AM -> OFF 3:14 PM must be ONE segment, 5h04m, never split by the hour boundaries it merely crosses', () => {
    const segs = mod.splitSpanByDay(ist('2026-08-13T10:10:00+05:30'), ist('2026-08-13T15:14:00+05:30'));
    expect(segs.length).toBe(1); // crossing 10,11,12,13,14,15 o'clock must NOT create multiple segments
    const totalSeconds = segs.reduce((a, s) => a + s.seconds, 0);
    expect(Math.round(totalSeconds)).toBe(5 * 3600 + 4 * 60); // 18240s, no double counting or loss
  });
  it('positive: a span crossing exactly one midnight splits into exactly 2 segments whose total equals the real duration', () => {
    const startMs = ist('2026-08-13T22:00:00+05:30');
    const endMs = ist('2026-08-14T02:00:00+05:30');
    const segs = mod.splitSpanByDay(startMs, endMs);
    expect(segs.length).toBe(2);
    expect(segs[0].dayKey).toBe('2026-08-13');
    expect(segs[1].dayKey).toBe('2026-08-14');
    const total = segs.reduce((a, s) => a + s.seconds, 0);
    expect(Math.round(total)).toBe(4 * 3600);
    expect(Math.round(segs[0].seconds)).toBe(2 * 3600);
    expect(Math.round(segs[1].seconds)).toBe(2 * 3600);
  });
  it('boundary: a span crossing multiple midnights (3 days) splits into exactly 3 segments summing to the real duration', () => {
    const startMs = ist('2026-08-11T12:00:00+05:30');
    const endMs = ist('2026-08-13T12:00:00+05:30'); // 48h, crosses 2 midnights -> 3 calendar days
    const segs = mod.splitSpanByDay(startMs, endMs);
    expect(segs.length).toBe(3);
    expect(segs.map((s) => s.dayKey)).toEqual(['2026-08-11', '2026-08-12', '2026-08-13']);
    expect(Math.round(segs.reduce((a, s) => a + s.seconds, 0))).toBe(48 * 3600);
  });
  it('boundary: exact midnight start (00:00:00 IST) does not spuriously create a zero-length leading segment', () => {
    const segs = mod.splitSpanByDay(ist('2026-08-13T00:00:00+05:30'), ist('2026-08-13T05:00:00+05:30'));
    expect(segs.length).toBe(1);
    expect(Math.round(segs[0].seconds)).toBe(5 * 3600);
  });
  it('negative: endMs <= startMs (zero or negative-length span) returns an empty array, never a negative/zero-duration segment', () => {
    expect(mod.splitSpanByDay(ist('2026-08-13T10:00:00+05:30'), ist('2026-08-13T10:00:00+05:30'))).toEqual([]);
    expect(mod.splitSpanByDay(ist('2026-08-13T10:00:00+05:30'), ist('2026-08-13T09:00:00+05:30'))).toEqual([]);
  });
});

describe('bucketSpansByDay — aggregates real spans into per-day totals (Heater ON Time / Machine Runtime shared bucketing)', () => {
  it('positive: multiple same-day spans sum correctly with no double counting', () => {
    const spans = [
      { startMs: ist('2026-08-13T09:00:00+05:30'), endMs: ist('2026-08-13T09:30:00+05:30') },
      { startMs: ist('2026-08-13T11:00:00+05:30'), endMs: ist('2026-08-13T11:45:00+05:30') },
    ];
    const result = mod.bucketSpansByDay(spans);
    expect(Math.round(result.totalSeconds)).toBe(75 * 60);
    expect(Math.round(result.byDay['2026-08-13'])).toBe(75 * 60);
  });
  it('positive: a midnight-crossing span correctly attributes its real share to BOTH days (never 100% to only the start day)', () => {
    const spans = [{ startMs: ist('2026-08-13T22:00:00+05:30'), endMs: ist('2026-08-14T02:00:00+05:30') }];
    const result = mod.bucketSpansByDay(spans);
    expect(Math.round(result.byDay['2026-08-13'])).toBe(2 * 3600);
    expect(Math.round(result.byDay['2026-08-14'])).toBe(2 * 3600);
    expect(Math.round(result.totalSeconds)).toBe(4 * 3600);
  });
  it('boundary: an empty spans array returns zero total and an empty day map', () => {
    const result = mod.bucketSpansByDay([]);
    expect(result.totalSeconds).toBe(0);
    expect(result.byDay).toEqual({});
  });
  it('negative: a zero-length span contributes nothing', () => {
    const result = mod.bucketSpansByDay([{ startMs: ist('2026-08-13T10:00:00+05:30'), endMs: ist('2026-08-13T10:00:00+05:30') }]);
    expect(result.totalSeconds).toBe(0);
  });
});

describe('dailyChartData — builds one bar per calendar day, including zero-activity days', () => {
  it('positive: fills every day in [fromTs, toTs] even when byDay has no entry for some (explicit 0 bar, not a silent gap)', () => {
    const fromTs = ist('2026-08-11T00:00:00+05:30');
    const toTs = ist('2026-08-13T23:59:59+05:30');
    const byDay = { '2026-08-11': 3600, '2026-08-13': 1800 };
    const result = mod.dailyChartData(byDay, fromTs, toTs);
    expect(result.labels.length).toBe(3);
    expect(result.seconds).toEqual([3600, 0, 1800]);
  });
  it('boundary: a single-day range returns exactly one bar', () => {
    const fromTs = ist('2026-08-13T00:00:00+05:30');
    const toTs = ist('2026-08-13T23:59:59+05:30');
    const result = mod.dailyChartData({ '2026-08-13': 100 }, fromTs, toTs);
    expect(result.labels.length).toBe(1);
    expect(result.seconds).toEqual([100]);
  });
});

describe('resolveBounds — date/time-range resolution (From/To -> epoch ms bounds)', () => {
  it('positive: an explicit From/To date+time pair resolves to the correct IST-anchored bounds', () => {
    const bounds = mod.resolveBounds({ fromDate: '2026-08-01', toDate: '2026-08-07', fromTime: '06:00', toTime: '18:00' });
    expect(bounds.fromTs).toBe(ist('2026-08-01T06:00:00+05:30'));
    expect(bounds.toTs).toBe(ist('2026-08-07T18:00:00+05:30') + 59999); // documented :59.999 inclusive-minute padding
  });
  it('boundary: no range at all (Clear / never-applied) falls back to "today" IST midnight -> now', () => {
    const before = Date.now();
    const bounds = mod.resolveBounds(null);
    const after = Date.now();
    expect(bounds.toTs).toBeGreaterThanOrEqual(before);
    expect(bounds.toTs).toBeLessThanOrEqual(after);
    expect(bounds.fromTs).toBeLessThan(bounds.toTs);
  });
  it('boundary: same From/To date (single-day custom range) resolves to a valid non-empty window', () => {
    const bounds = mod.resolveBounds({ fromDate: '2026-08-13', toDate: '2026-08-13', fromTime: '00:00', toTime: '23:59' });
    expect(bounds.toTs).toBeGreaterThan(bounds.fromTs);
  });
  it('negative: a From date with no To date defensively defaults rather than sending a malformed/NaN range', () => {
    const bounds = mod.resolveBounds({ fromDate: '2026-08-01', toDate: null, fromTime: '00:00', toTime: '23:59' });
    expect(bounds.fromTs).toBe(ist('2026-08-01T00:00:00+05:30'));
    expect(Number.isFinite(bounds.toTs)).toBe(true);
  });
});

describe('aggregateSlice — real-reading mean aggregation (Live Temperature Trend sampling)', () => {
  it('positive: averages a contiguous slice of real readings and uses the middle reading\'s real timestamp', () => {
    const rows = [
      { temperature: 70, recorded_at: '2026-08-13T10:00:00Z' },
      { temperature: 72, recorded_at: '2026-08-13T10:00:05Z' },
      { temperature: 74, recorded_at: '2026-08-13T10:00:10Z' },
    ];
    const agg = mod.aggregateSlice(rows);
    expect(agg.temperature).toBe(72);
    expect(agg.recorded_at).toBe('2026-08-13T10:00:05Z');
  });
  it('negative: a slice where every temperature is a non-numeric STRING returns null rather than fabricating a value', () => {
    const rows = [{ temperature: 'not-a-number', recorded_at: '2026-08-13T10:00:00Z' }, { temperature: 'also-bad', recorded_at: '2026-08-13T10:00:01Z' }];
    expect(mod.aggregateSlice(rows)).toBeNull();
  });
  it('negative: a slice where every temperature is UNDEFINED (field missing) returns null — Number(undefined) is NaN, correctly excluded', () => {
    const rows = [{ recorded_at: '2026-08-13T10:00:00Z' }, { temperature: undefined, recorded_at: '2026-08-13T10:00:01Z' }];
    expect(mod.aggregateSlice(rows)).toBeNull();
  });
  // DEFECT (documented, not silently accepted): Number(null) === 0 in
  // JavaScript, so aggregateSlice's `!isNaN(Number(t))` guard does NOT
  // exclude a null temperature — it silently counts it as a real 0°C
  // reading and includes it in the average. This differs from `undefined`
  // (correctly excluded, see above) purely because of this JS coercion
  // quirk, not a deliberate design choice documented anywhere in the code.
  // See the audit's Defects sheet for the full report — this test locks in
  // the ACTUAL current behavior (so a future accidental fix is visible as
  // a passing-test diff, not a silent behavior change) without pretending
  // it's correct.
  it('DEFECT: a null temperature is silently treated as a valid 0°C reading and skews the average (Number(null) === 0, not NaN)', () => {
    const rows = [{ temperature: 80, recorded_at: '2026-08-13T10:00:00Z' }, { temperature: null, recorded_at: '2026-08-13T10:00:01Z' }];
    const agg = mod.aggregateSlice(rows);
    // Documents the REAL current (buggy) behavior: (80 + 0) / 2 = 40, not
    // the honest average of the one genuinely valid reading (80).
    expect(agg.temperature).toBe(40);
  });
  it('boundary: an empty slice returns null, never NaN or a zero-value fabricated point', () => {
    expect(mod.aggregateSlice([])).toBeNull();
  });
  it('positive: a mix of valid and malformed rows averages only the valid ones', () => {
    const rows = [
      { temperature: 80, recorded_at: '2026-08-13T10:00:00Z' },
      { temperature: 'bad', recorded_at: '2026-08-13T10:00:01Z' },
      { temperature: 90, recorded_at: '2026-08-13T10:00:02Z' },
    ];
    expect(mod.aggregateSlice(rows).temperature).toBe(85);
  });
});

describe('buildOnlineSpans — Machine Runtime online/offline event pairing (defensive against messy real backend event streams)', () => {
  const bounds = { fromTs: ist('2026-08-13T00:00:00+05:30'), toTs: ist('2026-08-13T23:59:59+05:30') };
  const nowMs = ist('2026-08-13T18:00:00+05:30');

  it('positive: a clean ON->OFF pair produces exactly one span with the real timestamps', () => {
    const restarted = [{ created_at: '2026-08-13T09:00:00+05:30' }];
    const offline = [{ created_at: '2026-08-13T11:00:00+05:30' }];
    const spans = mod.buildOnlineSpans(offline, restarted, false, bounds, nowMs);
    expect(spans.length).toBe(1);
    expect(spans[0].startMs).toBe(ist('2026-08-13T09:00:00+05:30'));
    expect(spans[0].endMs).toBe(ist('2026-08-13T11:00:00+05:30'));
  });
  it('negative: duplicate ON events in a row (no OFF between) open only ONE span from the FIRST ON, ignoring the duplicate', () => {
    const restarted = [{ created_at: '2026-08-13T09:00:00+05:30' }, { created_at: '2026-08-13T09:05:00+05:30' }];
    const offline = [{ created_at: '2026-08-13T11:00:00+05:30' }];
    const spans = mod.buildOnlineSpans(offline, restarted, false, bounds, nowMs);
    expect(spans.length).toBe(1);
    expect(spans[0].startMs).toBe(ist('2026-08-13T09:00:00+05:30'));
  });
  it('negative: a stray OFF event with nothing open is ignored (no spurious zero/negative-length span)', () => {
    const spans = mod.buildOnlineSpans([{ created_at: '2026-08-13T11:00:00+05:30' }], [], false, bounds, nowMs);
    expect(spans.length).toBe(0);
  });
  it('boundary: an ongoing span (no matching OFF yet) is closed at "now" when now falls inside the range', () => {
    const spans = mod.buildOnlineSpans([], [{ created_at: '2026-08-13T09:00:00+05:30' }], false, bounds, nowMs);
    expect(spans.length).toBe(1);
    expect(spans[0].endMs).toBe(nowMs);
  });
  it('positive: wasOnlineAtStart=true opens an implicit span at the range\'s own fromTs', () => {
    const spans = mod.buildOnlineSpans([{ created_at: '2026-08-13T11:00:00+05:30' }], [], true, bounds, nowMs);
    expect(spans.length).toBe(1);
    expect(spans[0].startMs).toBe(bounds.fromTs);
    expect(spans[0].endMs).toBe(ist('2026-08-13T11:00:00+05:30'));
  });
  it('boundary: an event with an unparseable created_at is filtered out rather than corrupting the sort', () => {
    const restarted = [{ created_at: 'not-a-date' }, { created_at: '2026-08-13T09:00:00+05:30' }];
    const spans = mod.buildOnlineSpans([{ created_at: '2026-08-13T11:00:00+05:30' }], restarted, false, bounds, nowMs);
    expect(spans.length).toBe(1);
    expect(spans[0].startMs).toBe(ist('2026-08-13T09:00:00+05:30'));
  });
});

describe('dedupeCycles — Heater ON Time duplicate-record collapsing (regression: "Yesterday" range showing the same 10:10am cycle twice)', () => {
  // Root cause this guards against: fetchAllCyclesInRange's boundary probe
  // fetches one extra row via `offset = items.length` in the UNSCOPED
  // (unfiltered) heating-cycles list, on the assumption the scoped
  // (range-filtered) list is always a PREFIX of the unscoped one. That only
  // holds when the range's upper bound is "now" (Today/Last 7/Last 30). For
  // "Yesterday" (or any Custom Range not ending today), the scoped list is a
  // MIDDLE SLICE instead, so that offset can land back inside the
  // already-fetched slice and re-append a row already present — e.g. the
  // earliest (10:10am) cycle already in `items`. dedupeCycles is the actual
  // fix; these tests exercise it directly with the real duplicate shape.
  it('positive (regression): an exact re-fetched duplicate (same heater_on_at AND heater_off_at) collapses to one entry', () => {
    const a = { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: '2026-08-13T05:00:00Z' }; // 10:10am IST
    const b = { heater_on_at: '2026-08-13T09:46:00Z', heater_off_at: '2026-08-13T09:50:00Z' };
    const reFetchedA = { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: '2026-08-13T05:00:00Z' }; // boundary probe re-fetch of `a` — a DIFFERENT object, same values
    const out = mod.dedupeCycles([b, a, reFetchedA]); // boundary probe result is appended last, exactly as fetchAllCyclesInRange does
    expect(out.length).toBe(2);
    expect(out).toEqual([b, a]); // first occurrence wins; order otherwise preserved
  });
  it('negative: two genuinely distinct cycles sharing the same heater_on_at (displayed start time) but different heater_off_at both survive', () => {
    const first = { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: '2026-08-13T05:00:00Z' };
    const second = { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: '2026-08-13T06:30:00Z' }; // same start, real different end — a genuinely separate cycle
    const out = mod.dedupeCycles([first, second]);
    expect(out.length).toBe(2);
  });
  it('negative: two genuinely distinct cycles where only one is still ongoing (same start, one heater_off_at, one null) both survive', () => {
    const completed = { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: '2026-08-13T05:00:00Z' };
    const ongoing = { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: null };
    const out = mod.dedupeCycles([completed, ongoing]);
    expect(out.length).toBe(2);
  });
  it('positive: two ongoing rows with the identical heater_on_at and both heater_off_at null collapse (no better identity available, and a machine cannot have two truly concurrent ongoing cycles from the same start)', () => {
    const out = mod.dedupeCycles([
      { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: null },
      { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: null },
    ]);
    expect(out.length).toBe(1);
  });
  it('positive: duplicates are collapsed regardless of input order (out-of-order / overlapping API pages)', () => {
    const dup = { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: '2026-08-13T05:00:00Z' };
    const other = { heater_on_at: '2026-08-13T09:46:00Z', heater_off_at: '2026-08-13T09:50:00Z' };
    const out = mod.dedupeCycles([{ ...dup }, other, { ...dup }, { ...dup }]);
    expect(out.length).toBe(2);
  });
  it('boundary: an empty array returns an empty array', () => {
    expect(mod.dedupeCycles([])).toEqual([]);
  });
  it('boundary: a single cycle passes through unchanged', () => {
    const only = { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: '2026-08-13T05:00:00Z' };
    expect(mod.dedupeCycles([only])).toEqual([only]);
  });
  it('negative: no duplicates at all leaves every cycle intact, in the same order', () => {
    const cycles = [
      { heater_on_at: '2026-08-13T04:40:00Z', heater_off_at: '2026-08-13T05:00:00Z' },
      { heater_on_at: '2026-08-13T09:46:00Z', heater_off_at: '2026-08-13T09:50:00Z' },
      { heater_on_at: '2026-08-13T11:16:00Z', heater_off_at: null },
    ];
    expect(mod.dedupeCycles(cycles)).toEqual(cycles);
  });
});

describe('friendlyErrorFor — API error classification', () => {
  it('positive: a 404 status maps to a "not available" message', () => {
    expect(mod.friendlyErrorFor({ status: 404 })).toMatch(/not available/i);
  });
  it('positive: a 500 status maps to "temporarily unavailable"', () => {
    expect(mod.friendlyErrorFor({ status: 503 })).toMatch(/temporarily unavailable/i);
  });
  it('boundary: a 504/408 (timeout-shaped) status maps to a timeout-specific message', () => {
    expect(mod.friendlyErrorFor({ status: 504 })).toMatch(/did not respond in time/i);
    expect(mod.friendlyErrorFor({ status: 408 })).toMatch(/did not respond in time/i);
  });
  it('negative: an AbortError returns null (superseded request, never shown to the user)', () => {
    expect(mod.friendlyErrorFor({ name: 'AbortError' })).toBeNull();
  });
  it('negative: a network-shaped TypeError maps to a network-error message', () => {
    expect(mod.friendlyErrorFor({ name: 'TypeError', message: 'Failed to fetch' })).toMatch(/network/i);
  });
  it('boundary: an unrecognized error falls back to a generic message, never throws', () => {
    expect(mod.friendlyErrorFor({})).toBe('Unable to load analytics data.');
    expect(mod.friendlyErrorFor(null)).toBe('Unable to load analytics data.');
  });
});
