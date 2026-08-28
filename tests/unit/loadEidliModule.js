/*
 * Test harness for loading the REAL, unmodified Electric Idli Machine
 * front-end JS files (pos/static/js/eidli/*.js) into a jsdom sandbox and
 * pulling their private (closure-scoped) pure functions out for direct unit
 * testing — with ZERO changes to the production files on disk.
 *
 * How it works: each production file is a single self-invoking IIFE,
 * `(function () { ... })();`, exposing only `window.Eidli` /
 * `window.EidliHistory` as its public surface. To reach the internal
 * functions (splitSpanByDay, buildOnlineSpans, resolveBounds, ...) without
 * editing the file, this harness reads the file's source TEXT (unmodified),
 * then — only in this in-memory copy, never written back to disk — rewrites
 * the final `})();` into `return {...all internal names...}; })();` and
 * assigns the IIFE's result to a variable. The production file itself is
 * never touched; this is a pure test-time transformation of a string held
 * only in this process's memory, equivalent in spirit to a debug/test hook
 * but requiring no `if (typeof module...)` shim in the source at all.
 *
 * This is "option (b)" from the audit brief: real file, unmodified on disk,
 * loaded via a jsdom+script-eval harness.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { JSDOM } = require('jsdom');

const EIDLI_DIR = path.join(__dirname, '..', '..', 'static', 'js', 'eidli');

// Internal function names to expose from each file, for the harness's
// synthetic `return {...}` — every name here must be an actual top-level
// `function name(...)` declared inside that file's IIFE (verified by
// reading the real source; this list does not invent behavior).
const EXPORT_NAMES = {
  'history-analytics.js': [
    'splitSpanByDay', 'bucketSpansByDay', 'dailyChartData', 'buildOnlineSpans',
    'resolveBounds', 'fmtDurationHM', 'aggregateSlice', 'friendlyErrorFor',
    'dedupeCycles',
  ],
  'dashboard.js': [
    'computeStableYBounds',
  ],
  'history.js': [
    'validateDateRange',
  ],
  'core.js': [], // core.js already exposes everything needed via window.Eidli; no closure digging required
};

function loadSource(filename) {
  return fs.readFileSync(path.join(EIDLI_DIR, filename), 'utf8');
}

// Rewrites the trailing `})();` of the IIFE into a version that returns an
// object exposing the requested internal function names, and assigns the
// call's result to `window.__EIDLI_TEST_HOOK__`. Only ever applied to an
// in-memory string — the real file on disk is never modified.
function withTestHook(source, exportNames) {
  if (!exportNames.length) return source;
  const marker = /\}\)\(\);\s*$/;
  if (!marker.test(source)) {
    throw new Error('loadEidliModule: expected file to end with "})();" — harness assumption broken, refusing to guess.');
  }
  // Insert `return {...}` immediately before the IIFE's closing `})();` so
  // the call expression itself evaluates to the exports object, then
  // capture that into window.__EIDLI_TEST_HOOK__ by wrapping the whole
  // expression in an assignment. The IIFE's own source (the
  // `(function () { ... }` part and everything inside it) is otherwise
  // byte-for-byte identical to the real file.
  const returnStmt = `return { ${exportNames.join(', ')} };\n})();`;
  const withReturn = source.replace(marker, returnStmt);
  return `window.__EIDLI_TEST_HOOK__ = ${withReturn.replace(/;\s*$/, '')};`;
}

/**
 * Loads one or more real eidli/*.js files (by filename, e.g.
 * 'history-analytics.js') into a fresh jsdom window, wiring up whatever
 * globals that file expects (window.Eidli, window.EidliHistory, a `Chart`
 * stub, etc.) — same shape core.js/history.js/dashboard.js expect when
 * loaded in the real browser via <script> tags in this exact order.
 *
 * Returns { window, hooks } where hooks[filename] is the object of internal
 * functions exposed for that file (per EXPORT_NAMES above), or undefined
 * for files with none configured.
 */
function loadEidliModules(filenames, { configured = true } = {}) {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/machines/idli/history',
    runScripts: 'dangerously',
  });
  const window = dom.window;
  // core.js is `(function (window) { ... })(window);` — it references the
  // bare identifier `window` as its own IIFE parameter, which only resolves
  // correctly when the script actually runs INSIDE the jsdom window's own
  // global scope (so the global `window` self-reference jsdom provides is
  // in scope), not via a detached `vm` context. `runScripts: 'dangerously'`
  // plus `window.eval` (not Node's `vm.runInContext` on a separate
  // sandbox) is what makes that identifier resolve exactly like it does in
  // a real browser <script> tag.

  // Minimal EIDLI_CONFIG a real page would inject via its inline <script>
  // before core.js loads.
  window.EIDLI_CONFIG = {
    configured,
    urls: {
      machine: '/machines/idli/api/machine', status: '/machines/idli/api/status',
      settings: '/machines/idli/api/settings', temperatureLogs: '/machines/idli/api/temperature-logs',
      events: '/machines/idli/api/events', commands: '/machines/idli/api/commands',
      heatingCycles: '/machines/idli/api/heating-cycles', sessions: '/machines/idli/api/sessions',
    },
  };
  // Chart.js is loaded as a real <script> in production; a minimal
  // constructor stub is enough for functions that only ever call `new
  // Chart(...)`/`.destroy()` without this harness needing the real
  // charting library (none of the pure functions under test render a
  // chart — chart construction is incidental to loading the file, not to
  // what's being tested).
  window.Chart = function ChartStub() { this.destroy = function () {}; this.data = {}; this.options = { scales: { y: {} } }; };
  window.performance = window.performance || { now: () => Date.now() };
  window.fetch = window.fetch || (() => Promise.reject(new Error('fetch not stubbed in unit harness')));
  window.showToast = function () {};

  const hooks = {};
  filenames.forEach((filename) => {
    const exportNames = EXPORT_NAMES[filename] || [];
    const raw = loadSource(filename);
    const src = withTestHook(raw, exportNames);
    window.eval(src);
    if (exportNames.length) {
      hooks[filename] = window.__EIDLI_TEST_HOOK__;
      delete window.__EIDLI_TEST_HOOK__;
    }
  });

  return { window, hooks };
}

module.exports = { loadEidliModules };
