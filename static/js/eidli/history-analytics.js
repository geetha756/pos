/*
 * Electric Idli Machine — History page, "Analytics" tab (Machine Analytics
 * graph). Loaded alongside history.js, but deliberately kept in its own
 * file/IIFE — Events and Commands (owned by history.js) are not touched by
 * anything here.
 *
 * Shares the ONE page-level date range that history.js's Apply/Clear/preset
 * buttons already own (see window.EidliHistory in history.js) instead of
 * running a second, separate range picker: onRangeChange() below is called
 * every time that range actually changes, and this module reloads whichever
 * graph is selected against the new bounds — same range, same Apply/Clear/
 * preset UI Events and Commands already use.
 *
 * Graph type: exactly one — Live Temperature Trend — GET
 * /idli/api/temperature-logs, sampled the same way the Dashboard's own live
 * chart does (see dashboard.js): evenly-spaced windows, each point the mean
 * of a real contiguous slice of backend rows. Never fabricated/interpolated.
 *
 * The Machine Runtime graph option (built from the machine's connectivity
 * record — GET /idli/api/events filtered to machine_restarted/
 * machine_offline — bucketed into a bar chart via bucketSpansByDay/
 * durationBarChart) and the Graph Type combobox that switched between it
 * and Live Temperature Trend were removed from the product (History ->
 * Graph now shows only the Live Temperature Trend chart, with no
 * selector), the same way the Heater ON Time option was removed earlier —
 * see machine-analytics.spec.js's file header for that precedent. There is
 * only ever one graph type now, so there is nothing left to switch between
 * and no picker UI is rendered.
 *
 * Loading/race-safety: every fetch is tagged with a monotonically
 * increasing request id (requestSeq); a response is only ever applied to
 * the chart if it's still the newest request issued — so a rapid double
 * Refresh (or a range change while a load is in flight) can never have a
 * slow, stale response overwrite a faster, newer one. AbortController
 * additionally cancels the actual in-flight network request(s) for the
 * previous load the moment a new one is requested, rather than just
 * ignoring its result once it eventually lands.
 */
(function () {
    var E = window.Eidli;
    var el = E.el, esc = E.esc, apiFetch = E.apiFetch;
    var fmtTemp = E.fmtTemp;
    var URLS = E.URLS, CONFIGURED = E.CONFIGURED;
    var H = window.EidliHistory; // history.js's shared range module
    var TEMP_LINE_COLOR = E.TEMP_LINE_COLOR, TEMP_FILL_COLOR = E.TEMP_FILL_COLOR;
    var THRESHOLD_OFF_COLOR = E.THRESHOLD_OFF_COLOR, THRESHOLD_ON_COLOR = E.THRESHOLD_ON_COLOR;
    var buildTempChartConfig = E.tempTrendChartConfig;

    var IST_TZ = 'Asia/Kolkata';
    var ANALYTICS_TITLE = 'Live Temperature Trend';

    var currentBounds = null; // { fromTs, toTs } epoch ms, resolved from the shared range (or "today" if never applied)
    var chart = null;
    var requestSeq = 0; // bumped on every load; a response is only applied if it's still the latest
    var inFlightController = null; // AbortController for whatever fetch(es) requestSeq currently owns
    var loadInFlight = false;
    var pendingReload = null; // { bounds } — scheduled once the in-flight load settles, so a rapid double-trigger converges on the LAST requested bounds instead of stacking up
    var everLoaded = false; // first-load gate for the tab-activate lazy load

    // Includes seconds so a fast-polling series (Live Temperature Trend)
    // doesn't render several consecutive points under the same minute-only
    // label - see dashboard.js's fmtHM for the same fix and rationale.
    function fmtHM(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleTimeString('en-IN', { timeZone: IST_TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
    }
    function fmtDMY(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-IN', { timeZone: IST_TZ, day: '2-digit', month: 'short', year: 'numeric' });
    }
    // --- shared range resolution -------------------------------------------------

    // "Today" (IST calendar day) is the fallback whenever the shared range
    // has no explicit From/To set yet (Clear, or before the operator has
    // ever touched the controls this page-session) — matches what the
    // Dashboard's own live chart treats as its default window.
    function resolveBounds(range) {
        var now = new Date();
        if (!range || (!range.fromDate && !range.toDate)) {
            var todayIso = E.istDateISO(now);
            return { fromTs: new Date(todayIso + 'T00:00:00+05:30').getTime(), toTs: now.getTime() };
        }
        var fromTime = range.fromTime || '00:00';
        var toTime = range.toTime || '23:59';
        var fromTs = range.fromDate ? new Date(range.fromDate + 'T' + fromTime + ':00+05:30').getTime() : null;
        var toTs = range.toDate ? new Date(range.toDate + 'T' + toTime + ':59.999+05:30').getTime() : now.getTime();
        // A From with no To (shouldn't normally happen — history.js's own
        // validation requires both together for a real filter — but stay
        // defensive) defaults the missing side to "now"/epoch respectively
        // rather than sending a malformed request.
        if (fromTs === null) fromTs = 0;
        return { fromTs: fromTs, toTs: toTs };
    }

    // --- loading / empty / error state --------------------------------------------

    function setLoading(isLoading, label) {
        var overlay = el('eidli-analytics-chart-loading');
        var text = el('eidli-analytics-chart-loading-text');
        if (text) text.textContent = label || 'Loading analytics…';
        if (overlay) overlay.style.display = isLoading ? 'flex' : 'none';
    }
    function setEmpty(isEmpty, message) {
        var e = el('eidli-analytics-chart-empty');
        if (!e) return;
        if (message) e.textContent = message;
        e.style.display = isEmpty ? 'block' : 'none';
    }
    function setError(isError, message) {
        var e = el('eidli-analytics-chart-error');
        if (!e) return;
        if (message) e.textContent = message;
        e.style.display = isError ? 'block' : 'none';
    }
    function setSummary(html) {
        var s = el('eidli-analytics-summary');
        if (!s) return;
        if (!html) { s.style.display = 'none'; s.innerHTML = ''; return; }
        s.innerHTML = html;
        s.style.display = 'flex';
    }
    function summaryItem(label, value) {
        return '<div class="eidli-today-item"><div class="eidli-stat-label">' + esc(label) + '</div><div class="eidli-stat-value">' + esc(value) + '</div></div>';
    }

    function destroyChart() {
        if (chart) { chart.destroy(); chart = null; }
    }

    // --- retry wrapper (mirrors dashboard.js's apiFetchRetry) --------------------
    // This backend drops off the network briefly from time to time; retrying
    // up to twice (3 attempts total) with backoff absorbs a transient
    // hiccup instead of surfacing a confusing failure for what's really just
    // one slow round-trip. Respects `signal` so an aborted request (a newer
    // load superseding this one) stops retrying immediately instead of
    // continuing to hit the network for a result nobody wants anymore.
    function apiFetchRetry(url, signal, attempt) {
        attempt = attempt || 0;
        function retry() {
            if (signal && signal.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
            if (attempt >= 2) return apiFetch(url, { signal: signal });
            return new Promise(function (resolve, reject) {
                var t = setTimeout(resolve, 400 * (attempt + 1));
                if (signal) signal.addEventListener('abort', function () { clearTimeout(t); reject(new DOMException('Aborted', 'AbortError')); });
            }).then(function () { return apiFetchRetry(url, signal, attempt + 1); });
        }
        return apiFetch(url, { signal: signal }).then(function (res) {
            return (res.ok && res.body.success) ? res : retry();
        }).catch(function (err) {
            if (err && err.name === 'AbortError') throw err;
            return retry();
        });
    }

    // Wraps a failed (non-ok, or success:false) API response in a proper
    // Error carrying the HTTP status, so callers further up the chain
    // (friendlyErrorFor) can show a status-appropriate message instead of
    // one generic string for every failure kind.
    function apiError(res) {
        var err = new Error((res && res.body && res.body.message) || 'Request failed.');
        err.status = res && res.status;
        return err;
    }

    // ==============================================================================
    // Live Temperature Trend — reuses the exact sampling approach
    // dashboard.js's fetchChartData/sampleRange uses for its own live chart,
    // generalized to an arbitrary [fromTs, toTs] instead of always "today".
    // ==============================================================================

    var CHART_MAX_POINTS = 160;
    var CHART_SAMPLE_SIZE = 50;
    var POINTS_PER_WINDOW = 8;
    var CHART_FETCH_CONCURRENCY = 3;

    function aggregateSlice(rows) {
        var sum = 0, count = 0;
        for (var i = 0; i < rows.length; i++) {
            var t = Number(rows[i].temperature);
            if (!isNaN(t)) { sum += t; count++; }
        }
        if (!count) return null;
        return { temperature: sum / count, recorded_at: rows[Math.floor(rows.length / 2)].recorded_at };
    }

    function runLimited(items, limit, fn) {
        var results = new Array(items.length);
        var next = 0;
        function worker() {
            var i = next++;
            if (i >= items.length) return Promise.resolve();
            return fn(items[i]).then(function (r) { results[i] = r; return worker(); });
        }
        var workers = [];
        for (var w = 0; w < Math.min(limit, items.length); w++) workers.push(worker());
        return Promise.all(workers).then(function () { return results; });
    }

    function loadTemperatureTrend(bounds, signal) {
        var rangeQuery = '&start_time=' + encodeURIComponent(new Date(bounds.fromTs).toISOString()) +
            '&end_time=' + encodeURIComponent(new Date(bounds.toTs).toISOString());

        function probeUrl() { return URLS.temperatureLogs + '?limit=1&offset=0' + rangeQuery; }
        function pageUrl(offset) { return URLS.temperatureLogs + '?limit=' + CHART_SAMPLE_SIZE + '&offset=' + offset + rangeQuery; }

        function sampleRange(total) {
            var span = total;
            var count = Math.min(CHART_MAX_POINTS, span);
            var pageCount = Math.max(1, Math.min(Math.ceil(count / POINTS_PER_WINDOW), Math.ceil(span / CHART_SAMPLE_SIZE)));
            var maxPageStart = Math.max(0, total - 1 - CHART_SAMPLE_SIZE + 1);
            var pageStarts = [];
            for (var p = 0; p < pageCount; p++) {
                pageStarts.push(Math.round(0 + maxPageStart * p / Math.max(1, pageCount - 1)));
            }
            var pointsPerThisPage = Math.max(1, Math.round(count / pageCount));
            return runLimited(pageStarts, CHART_FETCH_CONCURRENCY, function (pageStart) {
                return apiFetchRetry(pageUrl(pageStart), signal).then(function (res) {
                    if (!res.ok || !res.body.success) return [];
                    var pageItems = (res.body.data && res.body.data.items) || [];
                    if (!pageItems.length) return [];
                    var picks = Math.min(pointsPerThisPage, pageItems.length);
                    var out = [];
                    for (var i = 0; i < picks; i++) {
                        var sliceStart = Math.floor(pageItems.length * i / picks);
                        var sliceEnd = Math.max(sliceStart + 1, Math.floor(pageItems.length * (i + 1) / picks));
                        var agg = aggregateSlice(pageItems.slice(sliceStart, sliceEnd));
                        if (agg) out.push(agg);
                    }
                    return out;
                });
            }).then(function (perPageResults) {
                return [].concat.apply([], perPageResults).filter(Boolean);
            });
        }

        return apiFetchRetry(probeUrl(), signal).then(function (res) {
            if (!res.ok || !res.body.success) throw apiError(res);
            var total = (res.body.data && res.body.data.total) || 0;
            if (!total) return { readings: [] };
            return sampleRange(total).then(function (readings) { return { readings: readings }; });
        }).then(function (result) {
            var readings = result.readings.slice().sort(function (a, b) { return new Date(a.recorded_at) - new Date(b.recorded_at); });
            return { type: 'temperature', readings: readings };
        });
    }

    // See dashboard.js's own safeTemp() for the full rationale — coerces to
    // a finite number or `null` (a real gap), NEVER to a fabricated 0.
    function safeTemp(raw) {
        if (raw === null || raw === undefined || raw === '') return null;
        var n = Number(raw);
        return isNaN(n) ? null : n;
    }

    function renderTemperatureTrend(result, settings) {
        var items = result.readings;
        if (!items.length) { destroyChart(); setEmpty(true); setSummary(null); return; }
        setEmpty(false);

        var isMultiDay = (currentBounds.toTs - currentBounds.fromTs) > 26 * 3600 * 1000;
        var labelFor = isMultiDay ? fmtDMY : fmtHM;
        var labels = items.map(function (r) { return labelFor(r.recorded_at); });
        var temps = items.map(function (r) { return safeTemp(r.temperature); });
        var validTemps = temps.filter(function (t) { return t !== null; });

        // tension/cubicInterpolationMode/spanGaps/point styling match the
        // Dashboard's own Live Temperature Trend chart exactly (see
        // dashboard.js's renderChart()) — same shared theme, see
        // core.js's tempTrendChartConfig.
        var datasets = [{
            label: 'Temperature (°C)', data: temps,
            borderColor: TEMP_LINE_COLOR, backgroundColor: TEMP_FILL_COLOR,
            borderWidth: 2.5, tension: 0.35, cubicInterpolationMode: 'monotone',
            fill: true, spanGaps: false,
            pointRadius: 0, pointHoverRadius: 4, pointHoverBackgroundColor: TEMP_LINE_COLOR,
            pointHoverBorderColor: '#ffffff', pointHoverBorderWidth: 2
        }];
        // Keep the existing threshold/reference lines, same as the
        // Dashboard's own Live Temperature Trend chart, whenever settings
        // are available — real configured thresholds, never invented.
        if (settings && settings.off_temperature != null) {
            datasets.push({ label: 'Heater Off (' + Number(settings.off_temperature).toFixed(1) + '°C)', data: temps.map(function () { return Number(settings.off_temperature); }), borderColor: THRESHOLD_OFF_COLOR, borderDash: [5, 4], borderWidth: 1.25, pointRadius: 0, tension: 0, fill: false });
        }
        if (settings && settings.on_temperature != null) {
            datasets.push({ label: 'Heater Restart (' + Number(settings.on_temperature).toFixed(1) + '°C)', data: temps.map(function () { return Number(settings.on_temperature); }), borderColor: THRESHOLD_ON_COLOR, borderDash: [5, 4], borderWidth: 1.25, pointRadius: 0, tension: 0, fill: false });
        }

        // Summary stats (Readings / Average / Min / Max) are computed only
        // from real, valid readings — a missing/invalid one is excluded
        // rather than counted as 0, which would otherwise skew Average and
        // falsely drag Min down.
        if (validTemps.length) {
            var avg = validTemps.reduce(function (a, b) { return a + b; }, 0) / validTemps.length;
            var min = Math.min.apply(null, validTemps), max = Math.max.apply(null, validTemps);
            setSummary(summaryItem('Readings', String(validTemps.length)) + summaryItem('Average', fmtTemp(avg)) + summaryItem('Min', fmtTemp(min)) + summaryItem('Max', fmtTemp(max)));
        } else {
            setSummary(null);
        }

        destroyChart();
        chart = new Chart(el('eidli-analytics-chart'), buildTempChartConfig(labels, datasets, null, function (ctx) {
            if (ctx.dataset.label !== 'Temperature (°C)') return ctx.dataset.label;
            var r = items[ctx.dataIndex];
            if (!r) return '';
            return [fmtTemp(r.temperature), fmtDMY(r.recorded_at), fmtHM(r.recorded_at)];
        }));
    }

    // --- settings (thresholds, for the temperature graph's reference lines) ------

    var cachedSettings = null;
    function fetchSettingsOnce() {
        if (cachedSettings || !URLS.settings) return Promise.resolve(cachedSettings);
        return apiFetch(URLS.settings).then(function (res) {
            if (res.ok && res.body.success) cachedSettings = res.body.data;
            return cachedSettings;
        }).catch(function () { return null; });
    }

    // --- orchestration -------------------------------------------------------------

    function friendlyErrorFor(err) {
        if (err && err.name === 'AbortError') return null; // superseded — never shown
        var status = err && err.status;
        if (status === 404) return 'This analytics data is not available from the machine service.';
        if (status === 504 || status === 408) return 'The machine service did not respond in time.';
        if (status && status >= 500) return 'The machine service is temporarily unavailable.';
        if (err && (err.name === 'TypeError' || /network|fetch/i.test(err.message || ''))) return 'Network error — could not reach the machine service.';
        return 'Unable to load analytics data.';
    }

    // The single entry point — called on: initial tab visit, range change
    // (Apply/Clear/preset), and manual Refresh. Every call gets its own
    // requestSeq + AbortController; only the response matching the CURRENT
    // (latest) requestSeq is ever applied to the DOM, and superseded
    // in-flight requests are actively aborted rather than just ignored, so
    // a slow stale response (e.g. from a rapid double Refresh) can never
    // overwrite a newer one and duplicate/overlapping network work is
    // cancelled promptly.
    function loadAnalytics() {
        if (!CONFIGURED) { setLoading(false); setError(true, 'Not connected.'); return; }

        // Cancel whatever the previous call started — a range change or
        // Refresh always wins over anything still in flight for a now-stale
        // request.
        if (inFlightController) inFlightController.abort();
        var controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        inFlightController = controller;

        var seq = ++requestSeq;
        loadInFlight = true;
        var bounds = currentBounds;

        setError(false);
        setEmpty(false);
        setLoading(true, 'Loading analytics…');
        var titleEl = el('eidli-analytics-title');
        if (titleEl) titleEl.textContent = ANALYTICS_TITLE;
        var refreshBtn = el('eidli-analytics-refresh');
        if (refreshBtn) refreshBtn.disabled = true;

        var t0 = performance.now();
        var signal = controller ? controller.signal : undefined;

        var loader = Promise.all([loadTemperatureTrend(bounds, signal), fetchSettingsOnce()]).then(function (r) { return { result: r[0], settings: r[1] }; });

        loader.then(function (payload) {
            if (seq !== requestSeq) return; // superseded — a newer load already owns the screen
            loadInFlight = false;
            setLoading(false);
            if (refreshBtn) refreshBtn.disabled = false;
            console.debug('[history-analytics-timing]', 'temperature', 'loaded in', (performance.now() - t0).toFixed(0), 'ms');
            renderTemperatureTrend(payload.result, payload.settings);
            if (pendingReload) { var p = pendingReload; pendingReload = null; currentBounds = p.bounds; loadAnalytics(); }
        }).catch(function (err) {
            if (seq !== requestSeq) return;
            loadInFlight = false;
            setLoading(false);
            if (refreshBtn) refreshBtn.disabled = false;
            if (err && err.name === 'AbortError') return; // superseded — this request's own controller was aborted, nothing to show
            destroyChart();
            setSummary(null);
            var message = friendlyErrorFor(err);
            if (message) setError(true, message);
            console.debug('[history-analytics-timing]', 'temperature', 'failed after', (performance.now() - t0).toFixed(0), 'ms:', err && err.message);
            if (pendingReload) { var p = pendingReload; pendingReload = null; currentBounds = p.bounds; loadAnalytics(); }
        });
    }

    // Debounced trigger for range changes and Refresh — coalesces a burst of
    // rapid changes (e.g. several quick preset clicks) into a single
    // NETWORK request for whatever the FINAL range actually is, instead of
    // firing one request per intermediate change. The loading indicator
    // itself is shown synchronously, not debounced — the spec requires it
    // to appear immediately on any triggering action, and a user watching
    // the range change should never see a stale chart sit still for 120ms
    // first.
    var triggerDebounceTimer = null;
    function scheduleLoad() {
        setLoading(true, 'Loading analytics…');
        setError(false);
        var titleEl = el('eidli-analytics-title');
        if (titleEl) titleEl.textContent = ANALYTICS_TITLE;

        if (triggerDebounceTimer) clearTimeout(triggerDebounceTimer);
        triggerDebounceTimer = setTimeout(function () {
            triggerDebounceTimer = null;
            if (loadInFlight) {
                // Record the latest requested bounds; the in-flight load's
                // own completion handler re-triggers once it settles, so
                // the final requested range always eventually wins without
                // ever stacking up parallel requests.
                pendingReload = { bounds: currentBounds };
                return;
            }
            loadAnalytics();
        }, 120);
    }

    // --- wiring ---------------------------------------------------------------------

    function onRangeChanged(range) {
        currentBounds = resolveBounds(range);
        scheduleLoad();
    }

    function init() {
        if (!el('eidli-analytics-chart')) return; // Analytics pane not on this page
        currentBounds = resolveBounds(H ? H.getRange() : null);

        var refreshBtn = el('eidli-analytics-refresh');
        if (refreshBtn) refreshBtn.addEventListener('click', function () { scheduleLoad(); });

        function loadOnce() {
            if (everLoaded) return;
            everLoaded = true;
            loadAnalytics();
        }

        if (H) {
            H.onRangeChange(onRangeChanged);
            // First visit to the Analytics tab loads the graph lazily,
            // matching Events/Commands' own "load on first visit" shape —
            // not eagerly on every page load, since the operator may never
            // open this tab in a given visit.
            H.onTabActivate('analytics', loadOnce);
            // Both this file and history.js bind their own DOMContentLoaded
            // listener; listeners fire in registration order, and this
            // script tag loads AFTER history.js's. So when the page opens
            // directly on the Analytics tab (?tab=analytics in the URL),
            // history.js's own DOMContentLoaded handler has ALREADY called
            // activateTab('analytics') — and fired the onTabActivate
            // notification above — before this init() function (and its
            // H.onTabActivate registration) ever runs. That first
            // notification is missed entirely, and with no other trigger
            // queued, the graph would never load. Covered by checking
            // whether the Analytics pane is already the visible one right
            // now and loading immediately in that case, instead of only
            // ever reacting to a FUTURE activation.
            var pane = document.querySelector('.eidli-hist-pane[data-pane="analytics"]');
            if (pane && pane.style.display !== 'none') loadOnce();
        } else {
            // Defensive fallback (history.js failed to load its export for
            // some reason) — still shows something rather than a
            // permanently blank tab.
            loadOnce();
        }
    }

    if (!CONFIGURED) {
        document.addEventListener('DOMContentLoaded', function () {
            setLoading(false);
            setError(true, 'Not connected.');
        });
        return;
    }

    document.addEventListener('DOMContentLoaded', init);
})();
