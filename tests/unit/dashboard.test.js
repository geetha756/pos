// Unit tests for pos/static/js/eidli/dashboard.js's computeStableYBounds —
// the Live Temperature Trend chart's stable-axis rounding logic (fixes the
// "graph jumps on every ~2s live tick" issue from an earlier change in this
// project: Chart.js's default behavior re-fits the y-axis tightly on every
// update() call, so a single new point could shift the axis by a fraction
// of a degree; this pads+rounds to a coarse step so it only actually moves
// on a genuine, meaningful swing).
//
// KNOWN COVERAGE LIMITATION (documented, not hidden): the real function
// also reads `lastSettings` (heater thresholds), a module-private closure
// variable dashboard.js exposes no setter for. Exercising the
// thresholds-included branch would require either modifying production
// code to add a setter (forbidden by this audit's rules) or driving it
// through a full page/DOM Playwright flow (covered separately — see the
// Playwright suite's dashboard chart-stability test). These unit tests
// exercise the temps-only path, which is still the majority of the
// function's real logic (padding, rounding, empty-input handling).
import { describe, it, expect, beforeAll } from 'vitest';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { loadEidliModules } = require('./loadEidliModule.js');

let mod;

beforeAll(() => {
  const { hooks } = loadEidliModules(['core.js', 'dashboard.js']);
  mod = hooks['dashboard.js'];
});

describe('computeStableYBounds — stable, padded, rounded Y-axis bounds (temps-only path; see file header for the settings-branch limitation)', () => {
  it('positive: a cluster of stable readings pads and rounds outward to a clean 5-degree-step band', () => {
    const bounds = mod.computeStableYBounds([74.9, 75.1, 75.3, 74.8, 75.0]);
    expect(bounds).not.toBeNull();
    expect(bounds.min % 5).toBe(0); // rounded to a clean step
    expect(bounds.max % 5).toBe(0);
    expect(bounds.min).toBeLessThanOrEqual(74.8);
    expect(bounds.max).toBeGreaterThanOrEqual(75.3);
  });
  it('positive: small jitter within an already-comfortable margin still rounds to the SAME band — this is the actual anti-jump fix', () => {
    const bandA = mod.computeStableYBounds([75.0]);
    const bandB = mod.computeStableYBounds([75.0, 75.2]); // one more nearly-identical reading appended, as a live nudge would do
    expect(bandB).toEqual(bandA); // must NOT shift for a sub-degree change
  });
  it('positive: a genuine large swing (well beyond the padding) DOES expand the band — real changes are never hidden', () => {
    const bandBefore = mod.computeStableYBounds([75.0]);
    const bandAfter = mod.computeStableYBounds([75.0, 30.0]); // a real, large drop
    expect(bandAfter.min).toBeLessThan(bandBefore.min);
  });
  it('boundary: an empty temps array (no settings either, in this harness) returns null rather than a fabricated 0-0 band', () => {
    expect(mod.computeStableYBounds([])).toBeNull();
  });
  it('boundary: a single reading still produces a valid padded band, not a zero-width one', () => {
    const bounds = mod.computeStableYBounds([80]);
    expect(bounds.max).toBeGreaterThan(bounds.min);
  });
});
