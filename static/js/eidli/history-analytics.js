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
 * Graph types (exactly three, per spec):
 *   - Live Temperature Trend — GET /idli/api/temperature-logs, sampled the
 *     same way the Dashboard's own live chart does (see dashboard.js):
 *     evenly-spaced windows, each point the mean of a real contiguous slice
 *     of backend rows. Never fabricated/interpolated.
 *   - Machine Runtime — the machine backend's session-tracking endpoints
 *     (GET /idli/api/sessions) were confirmed (direct probe against the
 *     live service) to return 404 - Not Found; there is no session concept
 *     left there to read runtime from, and this NEVER falls back to
 *     fabricating or repurposing unrelated data to fill that gap. Instead,
 *     "runtime" is built from the machine's own real connectivity record:
 *     GET /idli/api/events, filtered server-side to event_type=
 *     machine_restarted (telemetry resumed - machine reachable/online) and
 *     event_type=machine_offline (telemetry stopped - machine unreachable).
 *     A runtime span is exactly the real, backend-recorded time between one
 *     of those and the next - genuine data, not invented. See
 *     buildOnlineSpans() below for the exact pairing algorithm, including
 *     duplicate/out-of-order/missing-partner handling. If GET /sessions is
 *     ever restored backend-side, this file would need an explicit change
 *     to switch back to it - it does not silently happen on its own.
 *   - Heater ON Time — GET /idli/api/heating-cycles. Each row is one real
 *     heater_on_at -> heater_off_at cycle; ON time is summed from the
 *     actual timestamps, clipped to the selected range. An ongoing cycle
 *     (heater_off_at still null) is clipped at "now" instead of being
 *     dropped or invented an end time for.
 *
 * Both Machine Runtime and Heater ON Time split each real span across IST
 * calendar-day boundaries (see splitSpanByDay()) before bucketing into a
 * multi-day chart, so a span that runs past midnight contributes its ON
 * time to BOTH days it actually overlaps, in the correct proportion —
 * attributing 100% of a midnight-crossing span to only the day it started
 * on would silently misreport the following day as having zero activity
 * during that carried-over stretch.
 *
 * Loading/race-safety: every fetch is tagged with a monotonically
 * increasing request id (requestSeq); a response is only ever applied to
 * the chart if it's still the newest request issued — so rapid graph-type/
 * range switches can never have a slow, stale response overwrite a faster,
 * newer one. AbortController additionally cancels the actual in-flight
 * network request(s) for the previous graph/range the moment a new one is
 * requested, rather than just ignoring its result once it eventually lands.
 *
 * Graph Type control: a custom-scripted combobox (see initCombobox() and
 * idli_history.html), not a native <select> — a native select's own popup
 * is OS-rendered, and in this app was found to close unexpectedly on Arrow
 * Down (DOM work happening inside the select's `change` handler while the
 * browser's native popup is still open interrupts its own key-handling
 * loop in some environments). This version owns its entire open/close/
 * highlight/selection behavior in script, so it's guaranteed correct across
 * mouse, Arrow Up/Down, Enter, Escape, and outside-click.
 */
(function () {
    var E = window.Eidli;
    var el = E.el, esc = E.esc, apiFetch = E.apiFetch;
    var fmtTemp = E.fmtTemp;
    var URLS = E.URLS, CONFIGURED = E.CONFIGURED;
    var H = window.EidliHistory; // history.js's shared range module

    var IST_TZ = 'Asia/Kolkata';
    var GRAPH_TITLES = {
        temperature: 'Live Temperature Trend',
        runtime: 'Machine Runtime',
        heater: 'Heater ON Time'
    };

    var currentGraphType = 'temperature';
    var currentBounds = null; // { fromTs, toTs } epoch ms, resolved from the shared range (or "today" if never applied)
    var chart = null;
    var requestSeq = 0; // bumped on every load; a response is only applied if it's still the latest
    var inFlightController = null; // AbortController for whatever fetch(es) requestSeq currently owns
    var loadInFlight = false;
    var pendingReload = null; // { graphType, bounds } — sceduled once the in-flight load settles, so a rapid double-trigger converges on the LAST requested state instead of stacking up
    var everLoaded = false; // first-load gate for the tab-activate lazy load

    function fmtHM(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleTimeString('en-IN', { timeZone: IST_TZ, hour: '2-digit', minute: '2-digit', hour12: true });
    }
    function fmtDMY(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-IN', { timeZone: IST_TZ, day: '2-digit', month: 'short', year: 'numeric' });
    }
    function fmtDM(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-IN', { timeZone: IST_TZ, day: '2-digit', month: 'short' });
    }

    // Hours + minutes only (e.g. "2h 35m", "45m", "<1m") — the spec calls
    // for this exact shape for every duration shown in Runtime/Heater ON
    // Time, not core.js's shared fmtDuration() (which is seconds-precision,
    // "2h 35m 10s", and used elsewhere on this page group for event/command
    // detail text that this task doesn't touch). Kept local to this file so
    // that shared helper's existing callers are unaffected.
    function fmtDurationHM(totalSeconds) {
        if (totalSeconds === null || totalSeconds === undefined || isNaN(totalSeconds)) return '—';
        var totalMinutes = Math.round(Math.max(0, totalSeconds) / 60);
        if (totalMinutes <= 0) return totalSeconds > 0 ? '<1m' : '0m';
        var h = Math.floor(totalMinutes / 60);
        var m = totalMinutes % 60;
        if (h > 0) return h + 'h ' + (m > 0 ? (m < 10 ? '0' + m : m) + 'm' : '00m');
        return m + 'm';
    }

    // Splits one real [startMs, endMs) span into one entry per IST calendar
    // day it actually overlaps, each carrying only the seconds that fall on
    // that specific day. A span entirely within one day returns a single
    // entry unchanged; a span crossing one or more midnights returns one
    // entry per day crossed, so multi-day bucketing (renderHeaterOnTime,
    // renderMachineRuntime) can attribute a midnight-crossing span's ON/
    // online time to every day it genuinely spans, in the correct
    // proportion, rather than dumping all of it onto the start day alone.
    function splitSpanByDay(startMs, endMs) {
        var out = [];
        if (!(endMs > startMs)) return out;
        var cursor = startMs;
        var guard = 0; // hard safety cap — a single span can realistically cross at most a handful of days for anything this UI's ranges cover (max 30 days), so 400 iterations is far beyond any real case and only exists to make an unexpected date-math bug fail loud instead of hanging the tab.
        while (cursor < endMs && guard++ < 400) {
            var dayKey = E.istDateISO(new Date(cursor));
            var dayEndMs = new Date(dayKey + 'T23:59:59.999+05:30').getTime();
            var segEnd = Math.min(endMs, dayEndMs);
            out.push({ dayKey: dayKey, seconds: (segEnd - cursor) / 1000 });
            cursor = dayEndMs + 1; // first instant of the next IST day
        }
        return out;
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

    function renderTemperatureTrend(result, settings) {
        var items = result.readings;
        if (!items.length) { destroyChart(); setEmpty(true); setSummary(null); return; }
        setEmpty(false);

        var isMultiDay = (currentBounds.toTs - currentBounds.fromTs) > 26 * 3600 * 1000;
        var labelFor = isMultiDay ? fmtDMY : fmtHM;
        var labels = items.map(function (r) { return labelFor(r.recorded_at); });
        var temps = items.map(function (r) { return Number(r.temperature); });

        var datasets = [{ label: 'Temperature (°C)', data: temps, borderColor: '#ff8a3d', backgroundColor: 'rgba(255,138,61,.12)', borderWidth: 2, pointRadius: 0, tension: 0, fill: true }];
        // Keep the existing threshold/reference lines, same as the
        // Dashboard's own Live Temperature Trend chart, whenever settings
        // are available — real configured thresholds, never invented.
        if (settings && settings.off_temperature != null) {
            datasets.push({ label: 'Heater Off (' + Number(settings.off_temperature).toFixed(1) + '°C)', data: temps.map(function () { return Number(settings.off_temperature); }), borderColor: '#f04747', borderDash: [6, 4], borderWidth: 1, pointRadius: 0, fill: false });
        }
        if (settings && settings.on_temperature != null) {
            datasets.push({ label: 'Heater Restart (' + Number(settings.on_temperature).toFixed(1) + '°C)', data: temps.map(function () { return Number(settings.on_temperature); }), borderColor: '#4098ff', borderDash: [6, 4], borderWidth: 1, pointRadius: 0, fill: false });
        }

        var avg = temps.reduce(function (a, b) { return a + b; }, 0) / temps.length;
        var min = Math.min.apply(null, temps), max = Math.max.apply(null, temps);
        setSummary(summaryItem('Readings', String(items.length)) + summaryItem('Average', fmtTemp(avg)) + summaryItem('Min', fmtTemp(min)) + summaryItem('Max', fmtTemp(max)));

        var INK = '#a7b1bf', GRID = '#2c3644';
        destroyChart();
        chart = new Chart(el('eidli-analytics-chart'), {
            type: 'line', data: { labels: labels, datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: {
                    legend: { display: true, labels: { color: INK, boxWidth: 12, font: { size: 11 } } },
                    tooltip: {
                        callbacks: {
                            title: function () { return ''; },
                            label: function (ctx) {
                                if (ctx.dataset.label !== 'Temperature (°C)') return ctx.dataset.label;
                                var r = items[ctx.dataIndex];
                                if (!r) return '';
                                return [fmtTemp(r.temperature), fmtDMY(r.recorded_at), fmtHM(r.recorded_at)];
                            }
                        }
                    }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: INK, maxTicksLimit: 8, font: { size: 10 } } },
                    y: { grid: { color: GRID }, ticks: { color: INK, callback: function (v) { return v + '°C'; } } }
                }
            }
        });
    }

    // ==============================================================================
    // Heater ON Time — GET /idli/api/heating-cycles, real heater_on_at ->
    // heater_off_at spans, summed and bucketed. The endpoint filters on
    // heater_on_at only (confirmed via its OpenAPI contract), so a cycle
    // that started just before the range but is still running (or ended)
    // inside it would otherwise be missed — one extra single-row request
    // fetches the cycle immediately preceding the range to cover exactly
    // that edge, without paging through anything unbounded.
    // ==============================================================================

    var HEATING_CYCLES_PAGE = 500; // this backend's confirmed max `limit`

    function fetchAllCyclesInRange(bounds, signal) {
        var rangeQuery = '&start_time=' + encodeURIComponent(new Date(bounds.fromTs).toISOString()) +
            '&end_time=' + encodeURIComponent(new Date(bounds.toTs).toISOString());
        function pageUrl(offset) { return URLS.heatingCycles + '?limit=' + HEATING_CYCLES_PAGE + '&offset=' + offset + rangeQuery; }

        function fetchPage(offset, acc) {
            return apiFetchRetry(pageUrl(offset), signal).then(function (res) {
                if (!res.ok || !res.body.success) throw apiError(res);
                var data = res.body.data || {};
                var items = data.items || [];
                var total = data.total || 0;
                var next = acc.concat(items);
                if (next.length >= total || !items.length) return next;
                return fetchPage(offset + items.length, next);
            });
        }
        return fetchPage(0, []).then(function (items) {
            // One extra unscoped probe for the single cycle immediately
            // preceding this range (i.e. at offset == total in the FULL,
            // unfiltered list) — catches a cycle that started earlier but
            // overlaps into the range (still running, or ended inside it).
            // Uses the scoped total as the unscoped offset: everything
            // newer than the range's start already appears above it in the
            // newest-first ordering, so that many rows is exactly how far
            // to skip to land on the next-older (out-of-range-start) cycle.
            var boundaryUrl = URLS.heatingCycles + '?limit=1&offset=' + items.length;
            return apiFetchRetry(boundaryUrl, signal).then(function (res) {
                if (res.ok && res.body.success) {
                    var boundary = ((res.body.data || {}).items || [])[0];
                    if (boundary) {
                        var onMs = new Date(boundary.heater_on_at).getTime();
                        var offMs = boundary.heater_off_at ? new Date(boundary.heater_off_at).getTime() : null;
                        // Only relevant if it actually reaches into the
                        // range — still running (no off time yet) or its
                        // off time falls at/after the range's start.
                        if (!isNaN(onMs) && (offMs === null || offMs >= bounds.fromTs)) items = items.concat([boundary]);
                    }
                }
                return items;
            }).catch(function () { return items; }); // the boundary probe is a best-effort completeness improvement, not a correctness requirement — a failure here still leaves the properly-scoped items intact
        });
    }

    function loadHeaterOnTime(bounds, signal) {
        return fetchAllCyclesInRange(bounds, signal).then(function (cycles) {
            return { type: 'heater', cycles: cycles };
        });
    }

    // Bucket a set of real [startMs,endMs) spans into per-IST-day totals,
    // splitting any span that crosses midnight via splitSpanByDay() so both
    // days it actually spans get their true share. Shared by Heater ON Time
    // and Machine Runtime — the only difference between the two is what
    // produces the spans (heating-cycle rows vs. online/offline event
    // pairs), not how they're bucketed into a daily chart.
    function bucketSpansByDay(spans) {
        var byDay = {};
        var totalSeconds = 0;
        spans.forEach(function (span) {
            splitSpanByDay(span.startMs, span.endMs).forEach(function (seg) {
                if (seg.seconds <= 0) return;
                byDay[seg.dayKey] = (byDay[seg.dayKey] || 0) + seg.seconds;
                totalSeconds += seg.seconds;
            });
        });
        return { byDay: byDay, totalSeconds: totalSeconds };
    }

    // Builds one bar-chart dataset from a { dayKey: seconds } map, covering
    // every calendar day in [fromTs, toTs] — including days with zero
    // activity, shown as an explicit 0 bar rather than a gap, so the chart
    // reads as a complete daily timeline instead of silently skipping days
    // nothing happened on.
    function dailyChartData(byDay, fromTs, toTs) {
        var days = [];
        var cursor = fromTs;
        var guard = 0;
        while (cursor <= toTs && guard++ < 400) {
            var dayKey = E.istDateISO(new Date(cursor));
            if (days.indexOf(dayKey) === -1) days.push(dayKey);
            cursor = new Date(dayKey + 'T23:59:59.999+05:30').getTime() + 1;
        }
        var labels = days.map(function (d) { return fmtDM(d + 'T00:00:00+05:30'); });
        var seconds = days.map(function (d) { return byDay[d] || 0; });
        return { labels: labels, seconds: seconds };
    }

    // Bar sizing for every bar in both Heater ON Time and Machine Runtime
    // (the only two graphs that use durationBarChart): 50px whenever the
    // chart has room for it — e.g. Today/Yesterday/Custom Range's handful
    // of per-cycle bars, or a Last-7-Days week of daily bars. maxBarThickness
    // (a CAP, not a fixed size like barThickness) is what's used here
    // instead of a hard barThickness: at a wide range with many category
    // slots (Last 30 Days renders one bar per calendar day, ~30 of them —
    // see dailyChartData), forcing every bar to a hard 50px would overflow
    // the fixed-width chart and make Chart.js compress/overlap them into a
    // solid merged block. maxBarThickness instead lets Chart.js shrink
    // bars below the 50px cap ONLY when the category band genuinely can't
    // fit it, so bars always stay a consistent, clearly-separated size —
    // reaching the full 50px whenever there's room, never merging when
    // there isn't. categoryPercentage stays high so bars are still
    // centered in a wide-enough band with visible whitespace between them.
    var DURATION_BAR_MAX_THICKNESS_PX = 50; // exact width requested, used as a cap so bars never merge on wide ranges

    function durationBarChart(labels, seconds, color, fillColor) {
        var INK = '#a7b1bf', GRID = '#2c3644';
        destroyChart();
        chart = new Chart(el('eidli-analytics-chart'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Duration', data: seconds, backgroundColor: fillColor, borderColor: color, borderWidth: 1, borderRadius: 4,
                    maxBarThickness: DURATION_BAR_MAX_THICKNESS_PX, categoryPercentage: 0.9
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: function (ctx) { return fmtDurationHM(ctx.parsed.y); } } }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: INK, maxTicksLimit: 10, font: { size: 10 } } },
                    y: {
                        grid: { color: GRID }, beginAtZero: true,
                        ticks: { color: INK, callback: function (v) { return fmtDurationHM(v); } }
                    }
                }
            }
        });
    }

    function renderHeaterOnTime(result) {
        var cycles = result.cycles;
        if (!cycles.length) { destroyChart(); setEmpty(true); setSummary(null); return; }

        var isMultiDay = (currentBounds.toTs - currentBounds.fromTs) > 26 * 3600 * 1000;
        var spans = cycles.map(function (c) {
            var onMs = new Date(c.heater_on_at).getTime();
            var offMs = c.heater_off_at ? new Date(c.heater_off_at).getTime() : Date.now();
            if (isNaN(offMs)) offMs = Date.now();
            return {
                startMs: Math.max(onMs, currentBounds.fromTs),
                endMs: Math.min(offMs, currentBounds.toTs)
            };
        }).filter(function (s) { return isFinite(s.startMs) && s.endMs > s.startMs; });

        if (!spans.length) { destroyChart(); setEmpty(true, 'No heater activity in the selected range.'); setSummary(null); return; }
        setEmpty(false);

        var bucketed = bucketSpansByDay(spans);
        var completedCount = cycles.filter(function (c) { return c.heater_off_at; }).length;
        var ongoingCount = cycles.length - completedCount;
        setSummary(
            summaryItem('Total ON time', fmtDurationHM(bucketed.totalSeconds)) +
            summaryItem('Cycles', String(cycles.length)) +
            (ongoingCount ? summaryItem('Ongoing', String(ongoingCount)) : '')
        );

        if (isMultiDay) {
            // Bucket by IST calendar day (split across midnight where a
            // cycle actually spans it) so a multi-day range reads as a
            // complete bar-per-day trend instead of one flat number or a
            // day silently under/over-counted at its edges.
            var daily = dailyChartData(bucketed.byDay, currentBounds.fromTs, currentBounds.toTs);
            durationBarChart(daily.labels, daily.seconds, '#157a5e', 'rgba(21,122,94,.55)');
        } else {
            // Single-day view: one bar per real cycle (not per day, since
            // there's only one day) so individual heating cycles stay
            // visible rather than collapsing into a single total bar.
            // fetchAllCyclesInRange returns cycles newest-first, so sort
            // chronologically (oldest -> newest) here to make the timeline
            // read left-to-right rather than backwards.
            var orderedCycles = cycles.slice().sort(function (a, b) {
                return new Date(a.heater_on_at).getTime() - new Date(b.heater_on_at).getTime();
            });
            var labels = orderedCycles.filter(function (c) {
                var onMs = new Date(c.heater_on_at).getTime();
                var offMs = c.heater_off_at ? new Date(c.heater_off_at).getTime() : Date.now();
                return Math.min(offMs, currentBounds.toTs) > Math.max(onMs, currentBounds.fromTs);
            }).map(function (c) { return fmtHM(c.heater_on_at); });
            var seconds = orderedCycles.map(function (c) {
                var onMs = new Date(c.heater_on_at).getTime();
                var offMs = c.heater_off_at ? new Date(c.heater_off_at).getTime() : Date.now();
                return Math.max(0, Math.min(offMs, currentBounds.toTs) - Math.max(onMs, currentBounds.fromTs)) / 1000;
            }).filter(function (s) { return s > 0; });
            durationBarChart(labels, seconds, '#157a5e', 'rgba(21,122,94,.55)');
        }
    }

    // ==============================================================================
    // Machine Runtime — built from the machine's real connectivity record,
    // not from a session concept (GET /idli/api/sessions is confirmed 404 -
    // that endpoint no longer exists on the backend, and this deliberately
    // never falls back to fabricating/repurposing unrelated data to fill
    // that gap). "Runtime" here means genuine machine-reachable time: the
    // real span between the backend's own machine_restarted event
    // (telemetry resumed - online) and the next machine_offline event
    // (telemetry stopped - offline), both queried server-side from
    // GET /idli/api/events via event_type. Every span is backed by two real,
    // backend-recorded timestamps.
    // ==============================================================================

    var EVENTS_PAGE = 500; // this backend's confirmed max `limit` (matches heating-cycles')

    function fetchAllEventsOfType(eventType, bounds, signal) {
        var rangeQuery = '&event_type=' + encodeURIComponent(eventType) +
            '&start_time=' + encodeURIComponent(new Date(bounds.fromTs).toISOString()) +
            '&end_time=' + encodeURIComponent(new Date(bounds.toTs).toISOString());
        function pageUrl(offset) { return URLS.events + '?limit=' + EVENTS_PAGE + '&offset=' + offset + rangeQuery; }
        function fetchPage(offset, acc) {
            return apiFetchRetry(pageUrl(offset), signal).then(function (res) {
                if (!res.ok || !res.body.success) throw apiError(res);
                var data = res.body.data || {};
                var items = data.items || [];
                var total = data.total || 0;
                var next = acc.concat(items);
                if (next.length >= total || !items.length) return next;
                return fetchPage(offset + items.length, next);
            });
        }
        return fetchPage(0, []);
    }

    // The single event immediately before the range's start, of either
    // tracked type — tells us whether the machine was already online or
    // already offline at bounds.fromTs, the same "boundary" technique
    // fetchAllCyclesInRange() uses for heating cycles. offlineCount/
    // restartedCount are how many of each already landed inside the range
    // (their sum is exactly how many total events precede this probe in
    // the unfiltered, newest-first ordering).
    function fetchBoundaryState(offlineCount, restartedCount, signal) {
        var offset = offlineCount + restartedCount;
        return apiFetchRetry(URLS.events + '?limit=1&offset=' + offset, signal).then(function (res) {
            if (!res.ok || !res.body.success) return null;
            return ((res.body.data || {}).items || [])[0] || null;
        }).catch(function () { return null; });
    }

    function loadMachineRuntime(bounds, signal) {
        return Promise.all([
            fetchAllEventsOfType('machine_offline', bounds, signal),
            fetchAllEventsOfType('machine_restarted', bounds, signal)
        ]).then(function (results) {
            var offlineEvents = results[0], restartedEvents = results[1];
            return fetchBoundaryState(offlineEvents.length, restartedEvents.length, signal).then(function (boundary) {
                return { type: 'runtime', offlineEvents: offlineEvents, restartedEvents: restartedEvents, boundary: boundary };
            });
        });
    }

    // Pairs sorted ON (machine_restarted) and OFF (machine_offline) events
    // into real online spans, defensively — this backend's connectivity
    // events are not guaranteed clean:
    //   - duplicate ONs in a row (no OFF between them): only the FIRST one
    //     actually opens a span; later duplicates are ignored rather than
    //     opening a second, overlapping span.
    //   - duplicate/stray OFFs with no open span: ignored (nothing to close).
    //   - a span still open at the end of the input (still online, or the
    //     matching OFF hasn't happened/arrived yet): closed at `nowMs` if
    //     that falls within [fromTs, toTs], otherwise at `toTs` — never
    //     left open past "now" or invented an end time beyond the range.
    //   - if the range's first real event is an OFF (the machine was
    //     already online when the range started), `wasOnlineAtStart`
    //     (from the boundary probe) opens an implicit span at `fromTs`
    //     instead of that OFF being discarded as unmatched.
    function buildOnlineSpans(offlineEvents, restartedEvents, wasOnlineAtStart, bounds, nowMs) {
        var merged = offlineEvents.map(function (e) { return { type: 'off', ts: new Date(e.created_at).getTime() }; })
            .concat(restartedEvents.map(function (e) { return { type: 'on', ts: new Date(e.created_at).getTime() }; }))
            .filter(function (e) { return !isNaN(e.ts); })
            .sort(function (a, b) { return a.ts - b.ts; });

        var spans = [];
        var openStart = wasOnlineAtStart ? bounds.fromTs : null;
        merged.forEach(function (e) {
            if (e.type === 'on') {
                if (openStart === null) openStart = e.ts; // ignore a duplicate ON while already open
            } else { // 'off'
                if (openStart !== null) {
                    spans.push({ startMs: Math.max(openStart, bounds.fromTs), endMs: Math.min(e.ts, bounds.toTs) });
                    openStart = null;
                }
                // else: stray OFF with nothing open — ignored
            }
        });
        if (openStart !== null) {
            // Still online at the end of the queried events — close at
            // "now" if now falls inside the range (still genuinely
            // ongoing), otherwise at the range's own end.
            var closeAt = Math.min(bounds.toTs, Math.max(openStart, Math.min(nowMs, bounds.toTs)));
            spans.push({ startMs: Math.max(openStart, bounds.fromTs), endMs: closeAt });
        }
        return spans.filter(function (s) { return s.endMs > s.startMs; });
    }

    function renderMachineRuntime(result) {
        var boundary = result.boundary;
        // The boundary probe's event tells us the machine's state going
        // INTO the range: if the closest prior event was machine_offline,
        // the machine was offline at fromTs; if machine_restarted (or no
        // prior event at all — nothing recorded before this range, so
        // there's no evidence it was ever offline), treat it as online.
        // Only these two event types carry this meaning; anything else
        // found at that offset (any other event type) doesn't change
        // online/offline state and is treated as inconclusive - not online.
        var wasOnlineAtStart = !boundary || boundary.event_type === 'machine_restarted';
        if (boundary && boundary.event_type !== 'machine_restarted' && boundary.event_type !== 'machine_offline') {
            wasOnlineAtStart = false;
        }

        var spans = buildOnlineSpans(result.offlineEvents, result.restartedEvents, wasOnlineAtStart, currentBounds, Date.now());

        destroyChart();
        if (!spans.length) { setEmpty(true, 'No machine runtime recorded in the selected range.'); setSummary(null); return; }
        setEmpty(false);

        var isMultiDay = (currentBounds.toTs - currentBounds.fromTs) > 26 * 3600 * 1000;
        var bucketed = bucketSpansByDay(spans);
        setSummary(summaryItem('Total runtime', fmtDurationHM(bucketed.totalSeconds)) + summaryItem('Online periods', String(spans.length)));

        if (isMultiDay) {
            var daily = dailyChartData(bucketed.byDay, currentBounds.fromTs, currentBounds.toTs);
            durationBarChart(daily.labels, daily.seconds, '#157a5e', 'rgba(21,122,94,.55)');
        } else {
            var labels = spans.map(function (s) { return fmtHM(new Date(s.startMs).toISOString()); });
            var seconds = spans.map(function (s) { return (s.endMs - s.startMs) / 1000; });
            durationBarChart(labels, seconds, '#157a5e', 'rgba(21,122,94,.55)');
        }
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

    // The single entry point — called on: initial tab visit, graph-type
    // change, range change (Apply/Clear/preset), and manual Refresh. Every
    // call gets its own requestSeq + AbortController; only the response
    // matching the CURRENT (latest) requestSeq is ever applied to the DOM,
    // and superseded in-flight requests are actively aborted rather than
    // just ignored, so a slow stale response can never overwrite a newer
    // one and duplicate/overlapping network work is cancelled promptly.
    function loadAnalytics() {
        if (!CONFIGURED) { setLoading(false); setError(true, 'Not connected.'); return; }

        // Cancel whatever the previous call started — a graph-type switch,
        // range change, or Refresh always wins over anything still in
        // flight for a now-stale selection.
        if (inFlightController) inFlightController.abort();
        var controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        inFlightController = controller;

        var seq = ++requestSeq;
        loadInFlight = true;
        var bounds = currentBounds;
        var graphType = currentGraphType;

        setError(false);
        setEmpty(false);
        setLoading(true, 'Loading analytics…');
        var titleEl = el('eidli-analytics-title');
        if (titleEl) titleEl.textContent = GRAPH_TITLES[graphType] || 'Analytics';
        var refreshBtn = el('eidli-analytics-refresh');
        if (refreshBtn) refreshBtn.disabled = true;

        var t0 = performance.now();
        var signal = controller ? controller.signal : undefined;

        var loader = graphType === 'temperature' ? Promise.all([loadTemperatureTrend(bounds, signal), fetchSettingsOnce()]).then(function (r) { return { result: r[0], settings: r[1] }; })
            : graphType === 'heater' ? loadHeaterOnTime(bounds, signal).then(function (r) { return { result: r }; })
            : loadMachineRuntime(bounds, signal).then(function (r) { return { result: r }; });

        loader.then(function (payload) {
            if (seq !== requestSeq) return; // superseded — a newer load already owns the screen
            loadInFlight = false;
            setLoading(false);
            if (refreshBtn) refreshBtn.disabled = false;
            console.debug('[history-analytics-timing]', graphType, 'loaded in', (performance.now() - t0).toFixed(0), 'ms');
            if (graphType === 'temperature') renderTemperatureTrend(payload.result, payload.settings);
            else if (graphType === 'heater') renderHeaterOnTime(payload.result);
            else renderMachineRuntime(payload.result);
            if (pendingReload) { var p = pendingReload; pendingReload = null; currentGraphType = p.graphType; currentBounds = p.bounds; loadAnalytics(); }
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
            console.debug('[history-analytics-timing]', graphType, 'failed after', (performance.now() - t0).toFixed(0), 'ms:', err && err.message);
            if (pendingReload) { var p = pendingReload; pendingReload = null; currentGraphType = p.graphType; currentBounds = p.bounds; loadAnalytics(); }
        });
    }

    // Debounced trigger for range/graph-type changes — coalesces a burst of
    // rapid changes (e.g. arrow-keying through the Graph Type dropdown, or
    // several quick preset clicks) into a single NETWORK request for
    // whatever the FINAL selection actually is, instead of firing one
    // request per intermediate change. The loading indicator itself is
    // shown synchronously, not debounced — the spec requires it to appear
    // immediately on any triggering action, and a user watching the graph
    // type flip should never see a stale chart sit still for 120ms first.
    var triggerDebounceTimer = null;
    function scheduleLoad() {
        setLoading(true, 'Loading analytics…');
        setError(false);
        var titleEl = el('eidli-analytics-title');
        if (titleEl) titleEl.textContent = GRAPH_TITLES[currentGraphType] || 'Analytics';

        if (triggerDebounceTimer) clearTimeout(triggerDebounceTimer);
        triggerDebounceTimer = setTimeout(function () {
            triggerDebounceTimer = null;
            if (loadInFlight) {
                // Record the latest requested state; the in-flight load's
                // own completion handler re-triggers once it settles, so
                // the final requested combination always eventually wins
                // without ever stacking up parallel requests.
                pendingReload = { graphType: currentGraphType, bounds: currentBounds };
                return;
            }
            loadAnalytics();
        }, 120);
    }

    // --- Graph Type combobox (custom, replaces a native <select>) ----------------
    //
    // WAI-ARIA 1.2 "Select-Only" combobox pattern: a button
    // (aria-haspopup="listbox", aria-expanded) toggles a role="listbox"
    // popup of role="option" items. Fully self-contained — owns its own
    // open/closed state, keyboard handling, and outside-click detection —
    // specifically so its behavior can be guaranteed rather than inherited
    // from an OS-rendered native <select> popup (see the file header
    // comment for why that was unreliable here).
    //
    // Keyboard contract (all verified in initCombobox/onComboboxKeydown):
    //   Arrow Down / Arrow Up  — when closed: opens AND moves the active
    //                            option; when open: moves the active
    //                            option only — NEVER closes the popup.
    //   Enter / Space          — when closed: opens; when open: commits the
    //                            active option (fires the same change path
    //                            a mouse click would) and closes.
    //   Escape                 — closes without changing the selection.
    //   Tab                    — closes without changing the selection and
    //                            lets focus move on normally (not trapped).
    //   Home / End              — jumps the active option to the first/last.
    //   click outside          — closes without changing the selection.
    //   click on trigger        — toggles open/closed.
    //   click on an option      — commits that option and closes.
    function initCombobox(rootId, onSelect) {
        var root = el(rootId);
        if (!root) return null;
        var trigger = root.querySelector('.eidli-combobox-trigger');
        var valueEl = root.querySelector('#' + rootId + '-value') || trigger.querySelector('span');
        var listbox = root.querySelector('.eidli-combobox-listbox');
        var options = Array.prototype.slice.call(root.querySelectorAll('.eidli-combobox-option'));
        var isOpen = false;
        var activeIndex = -1;

        function selectedIndex() {
            for (var i = 0; i < options.length; i++) if (options[i].getAttribute('aria-selected') === 'true') return i;
            return 0;
        }

        function setActive(index) {
            activeIndex = Math.max(0, Math.min(options.length - 1, index));
            options.forEach(function (o, i) { o.classList.toggle('eidli-combobox-active', i === activeIndex); });
            var activeOpt = options[activeIndex];
            if (activeOpt) {
                listbox.setAttribute('aria-activedescendant', activeOpt.id || '');
                activeOpt.scrollIntoView({ block: 'nearest' });
            }
        }

        function open() {
            if (isOpen) return;
            isOpen = true;
            listbox.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            setActive(selectedIndex());
            document.addEventListener('mousedown', onDocMouseDown, true);
            document.addEventListener('keydown', onDocKeydownCapture, true);
        }

        function close() {
            if (!isOpen) return;
            isOpen = false;
            listbox.hidden = true;
            trigger.setAttribute('aria-expanded', 'false');
            document.removeEventListener('mousedown', onDocMouseDown, true);
            document.removeEventListener('keydown', onDocKeydownCapture, true);
        }

        function commit(index) {
            var opt = options[index];
            if (!opt) return;
            options.forEach(function (o) { o.setAttribute('aria-selected', 'false'); });
            opt.setAttribute('aria-selected', 'true');
            if (valueEl) valueEl.textContent = opt.textContent.replace(/\s*✓\s*$/, '');
            close();
            trigger.focus();
            onSelect(opt.getAttribute('data-value'));
        }

        // Outside-click: closes without changing the selection. Uses
        // mousedown (not click) so it fires before a click on the trigger
        // itself would otherwise re-toggle it open in the same gesture.
        function onDocMouseDown(e) {
            if (root.contains(e.target)) return;
            close();
        }

        // Captured at the document level (not just on the trigger/listbox)
        // so Arrow Down/Up/Enter/Escape all work regardless of exactly
        // which element inside the combobox currently has focus, and so
        // this can intercept them before any other page-level handler.
        function onDocKeydownCapture(e) {
            if (!isOpen) return;
            switch (e.key) {
                case 'ArrowDown': e.preventDefault(); setActive(activeIndex + 1); break;
                case 'ArrowUp': e.preventDefault(); setActive(activeIndex - 1); break;
                case 'Home': e.preventDefault(); setActive(0); break;
                case 'End': e.preventDefault(); setActive(options.length - 1); break;
                case 'Enter':
                case ' ':
                    e.preventDefault();
                    // This capture handler commits and closes the popup.
                    // Stop the same key event reaching the trigger's
                    // closed-state keydown handler, which would otherwise
                    // immediately reopen it after commit().
                    e.stopPropagation();
                    commit(activeIndex);
                    break;
                case 'Escape':
                    e.preventDefault();
                    close();
                    trigger.focus();
                    break;
                case 'Tab':
                    close(); // don't trap focus — let Tab continue normally
                    break;
                default: break;
            }
        }

        trigger.addEventListener('click', function () {
            if (isOpen) close(); else open();
        });
        // Arrow Down/Up while the trigger itself has focus and the popup is
        // still CLOSED should open it (standard combobox/native-select
        // behavior) — the capture-phase handler above only runs once
        // isOpen is already true, so this covers the closed->open step.
        trigger.addEventListener('keydown', function (e) {
            if (isOpen) return; // already handled by onDocKeydownCapture
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                open();
            }
        });
        options.forEach(function (opt, i) {
            opt.addEventListener('click', function () { commit(i); });
            opt.addEventListener('mouseenter', function () { setActive(i); });
        });

        return {
            getValue: function () {
                var opt = options[selectedIndex()];
                return opt ? opt.getAttribute('data-value') : null;
            }
        };
    }

    // --- wiring ---------------------------------------------------------------------

    var graphTypeCombobox = null;

    function onRangeChanged(range) {
        currentBounds = resolveBounds(range);
        scheduleLoad();
    }

    function init() {
        if (!el('eidli-analytics-chart')) return; // Analytics pane not on this page
        currentBounds = resolveBounds(H ? H.getRange() : null);

        graphTypeCombobox = initCombobox('eidli-analytics-graph-type', function (value) {
            currentGraphType = value || 'temperature';
            scheduleLoad();
        });
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
