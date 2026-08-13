/*
 * Electric Idli Machine — Dashboard page.
 *
 * Live-update strategy:
 *   - /status polled every 3s, owned by core.js's shared header loop —
 *     this page just subscribes via Eidli.onStatus() instead of opening a
 *     second interval against the same endpoint. Drives machine/heater/
 *     sensor/online state (renderStatusGrid) — NOT the temperature value
 *     itself, see below.
 *   - Live temperature number (status grid + hero) is deliberately NOT
 *     sourced from /status: that endpoint's current_temperature was found
 *     (empirically, by direct side-by-side polling) to run 1.5-3.6s staler
 *     than the newest row already available from /temperature-logs, and
 *     the lag reproduces even calling the machine backend directly,
 *     bypassing every cache this app has — so it's inherent to /status on
 *     the backend, not fixable by polling it faster. Instead,
 *     refreshLiveTemperature() polls /temperature-logs?limit=1 on its own
 *     ~2s timer (see LIVE_TEMP_POLL_MS) and is the sole source for both the
 *     hero/grid number and the newest point nudged onto the Live
 *     Temperature Trend chart — so the two can never disagree about "now".
 *     See renderTempDisplay() and refreshLiveTemperature() for the full
 *     mechanism, including the monotonic recorded_at guard
 *     (payload-timestamp-driven, not request-order-driven) against a
 *     slow/out-of-order response regressing the display to an older
 *     reading.
 *   - the Live Temperature Trend chart shows only the current day's live
 *     telemetry (no historical date-range picker) — backfilled once on
 *     load, nudged forward on every live-temperature tick, and given a
 *     full authoritative re-fetch every 20s so it can never drift from
 *     what the backend actually has.
 *   - settings (thresholds): on load + manual refresh only.
 */
(function () {
    var E = window.Eidli;
    var el = E.el, esc = E.esc, apiFetch = E.apiFetch, errMsg = E.errMsg;
    var fmtTemp = E.fmtTemp, fmtRelative = E.fmtRelative;
    var URLS = E.URLS, CONFIGURED = E.CONFIGURED;

    var lastSettings = null;
    var lastLiveTemp = null; // { temperature, recorded_at } - the freshest temperature-logs record seen so far
    var lastLiveTempMs = null; // recorded_at as epoch ms, for the monotonic guard
    var tempChart = null;
    var chartItems = [];
    var chartFetchInFlight = false;
    var rangeFromTs = null, rangeToTs = null; // always today's bounds — see computeTodayBounds()
    // Set when a fetchChartData() call arrives while another is already in
    // flight — instead of just dropping it, one more fetch runs once the
    // in-flight one settles. Rapidly-firing triggers (manual refresh landing
    // mid-poll, etc.) this way converge on one trailing refetch instead of
    // queuing one per trigger.
    var pendingChartRefresh = false;
    function runPendingChartRefresh() {
        if (pendingChartRefresh) { pendingChartRefresh = false; fetchChartData(true); }
    }
    var CHART_MAX_POINTS = 160; // visual point budget for the chart; each point is an honest average of a slice of real backend records — see aggregateSlice
    // One-shot flag for the requested initial-load timing instrumentation
    // (temporary, per the investigation ask — safe to remove once load time
    // is confirmed fixed). Guards against re-logging on every subsequent
    // live poll, only the FIRST live response after page open matters here.
    var firstLiveStatusLogged = false;

    // --- fault banner (Priority 1) ------------------------------------------

    function renderFaultBanner(status) {
        var b = el('eidli-fault-banner');
        if (!CONFIGURED) {
            b.innerHTML = '';
            return;
        }
        var messages = [];
        if (!status || status.is_online === undefined) {
            // still loading — say nothing yet, avoid a false "offline" flash
        } else if (!status.is_online) {
            messages.push({ cls: 'eidli-alert-bad', icon: 'ri-wifi-off-line', text: 'Machine Offline — last telemetry ' + fmtRelative(status.last_seen) + '. Temperature shown is the last known reading, not current.' });
        }
        if (status) {
            var sensor = (status.sensor_status || '').toLowerCase();
            if (sensor === 'error') messages.push({ cls: 'eidli-alert-bad', icon: 'ri-error-warning-line', text: 'Temperature Sensor Fault — readings may be unreliable.' });
            else if (sensor === 'disconnected') messages.push({ cls: 'eidli-alert-warn', icon: 'ri-alert-line', text: 'Temperature Sensor Disconnected — temperature monitoring unavailable.' });
            if ((status.machine_status || '').toLowerCase() === 'fault') {
                messages.push({ cls: 'eidli-alert-bad', icon: 'ri-error-warning-line', text: 'Machine Fault reported by the machine service.' });
            }
        }
        b.innerHTML = messages.map(function (m) {
            return '<div class="eidli-alert ' + m.cls + '" role="alert"><i class="' + m.icon + '"></i><div>' + esc(m.text) + '</div></div>';
        }).join('');
    }

    // --- status grid (Priority 2/3) -----------------------------------------

    // Cached in sessionStorage so the NEXT time this page opens within the
    // same browser tab/session (e.g. Dashboard -> History -> Dashboard),
    // hydrateFromCache() below can paint these last-known values instantly,
    // before the first real network round-trip even starts, instead of
    // showing placeholders again.
    function cacheStatus(status) {
        try { sessionStorage.setItem('eidli_cache_status', JSON.stringify(status)); } catch (e) {}
    }

    function renderStatusGrid(status) {
        cacheStatus(status);
        el('eidli-grid-machine').innerHTML = E.machineStateBadge(status.machine_status);
        el('eidli-grid-heater').innerHTML = E.heaterBadge(status.heater_status);
        el('eidli-grid-sensor').innerHTML = E.sensorBadge(status.sensor_status);
        renderFaultBanner(status);
        // Re-paints the temperature display with whatever reading we
        // already have, under the freshly-updated online/offline label -
        // see renderTempDisplay()'s own comment for why the temperature
        // VALUE itself is deliberately not sourced from `status` here.
        renderTempDisplay();
    }

    // --- live temperature (authoritative source) -----------------------------
    //
    // /status's current_temperature is measurably staler than the newest row
    // already in temperature-logs: confirmed empirically (repeated
    // side-by-side polling) that /status's last_seen consistently lags
    // 1.5-3.6s behind temperature-logs' newest recorded_at - and calling the
    // backend's /status directly, bypassing every cache this app has,
    // reproduces the exact same lag. So the staleness is inherent to that
    // endpoint on the separate machine backend, not something introduced by
    // this app's own polling or caching (confirmed, not guessed - see the
    // investigation this fix was based on). temperature-logs is also the
    // faster-responding endpoint of the two. It's therefore used as the
    // sole source for the live temperature number (hero + stat grid) AND
    // the chart's live point, so both always agree - status stays
    // authoritative for heater/sensor/machine/online state, none of which
    // showed this same gap.
    function cacheLiveTemp(reading) {
        try { sessionStorage.setItem('eidli_cache_live_temp', JSON.stringify(reading)); } catch (e) {}
    }

    function renderTempDisplay() {
        el('eidli-grid-temp').textContent = lastLiveTemp ? fmtTemp(lastLiveTemp.temperature) : '—';
    }

    var LIVE_TEMP_POLL_MS = 2000; // close to the ESP32's own 1s telemetry cadence without over-polling a value this cheap to fetch (temperature-logs?limit=1 is a single-row read)

    var liveTempFetchInFlight = false;

    function refreshLiveTemperature() {
        if (!CONFIGURED) return;
        // Skip this tick entirely if the previous poll's request hasn't
        // landed yet, rather than firing another one on top of it. Without
        // this, a request that's taking a while (e.g. queued behind the
        // chart's own burst of requests — see sampleRange below, at the
        // browser's per-origin connection limit) would get a fresh
        // duplicate fired every single interval tick on top of it, and
        // those pile up faster than they can ever drain — the exact
        // opposite of what a live-freshness poll is for.
        if (liveTempFetchInFlight) return;
        liveTempFetchInFlight = true;
        // priority: 'high' additionally helps this single-row request jump
        // ahead of chart requests still waiting for a connection slot
        // (though not ones already in flight) — a small assist on top of
        // the in-flight guard above, not a substitute for it.
        //
        // No request-sequence guard on the response itself: the
        // recorded_at monotonic check below is the correct race guard —
        // driven by the payload's own timestamp rather than request
        // ordering, it accepts any response carrying a genuinely newer
        // reading and only rejects one that would regress the display to
        // an equal-or-older point.
        apiFetch(URLS.temperatureLogs + '?limit=1&offset=0', { priority: 'high' }).then(function (res) {
            liveTempFetchInFlight = false;
            if (!res.ok || !res.body.success) return;
            var items = (res.body.data && res.body.data.items) || [];
            if (!items.length) return;
            var latest = items[0];
            var recordedMs = new Date(latest.recorded_at).getTime();
            if (isNaN(recordedMs)) return;
            // Never let a response regress the displayed reading to a point
            // at or before the one already showing (out-of-order arrival,
            // or the backend simply hasn't recorded a newer one yet).
            if (lastLiveTempMs !== null && recordedMs <= lastLiveTempMs) return;
            lastLiveTempMs = recordedMs;
            lastLiveTemp = { temperature: latest.temperature, recorded_at: latest.recorded_at };
            cacheLiveTemp(lastLiveTemp);
            renderTempDisplay();

            // Nudge the Live Temperature Trend chart forward with this same
            // point instead of waiting for its own 20s full refetch, so the
            // chart's newest point and the hero number can never disagree
            // about what "now" actually reads.
            if (!chartFetchInFlight) {
                var lastPoint = chartItems.length ? chartItems[chartItems.length - 1] : null;
                var lastPointMs = lastPoint ? new Date(lastPoint.recorded_at).getTime() : -Infinity;
                if (recordedMs > lastPointMs) {
                    chartItems = chartItems.concat([{ recorded_at: latest.recorded_at, temperature: latest.temperature }]);
                    renderChart();
                }
            }
        }).catch(function () { liveTempFetchInFlight = false; });
    }

    // --- settings-derived: thresholds ------------------------------------------

    function renderThresholdsAndMode() {
        if (!lastSettings) return;
        el('eidli-threshold-off').textContent = fmtTemp(lastSettings.off_temperature);
        el('eidli-threshold-restart').textContent = fmtTemp(lastSettings.on_temperature);
    }

    var settingsRetryTimer = null;

    function refreshSettings() {
        if (!CONFIGURED) return;
        apiFetch(URLS.settings).then(function (res) {
            if (!res.ok || !res.body.success) {
                el('eidli-settings-error').innerHTML = '<div class="eidli-section-error">Couldn\'t load settings — will retry.</div>';
                if (!settingsRetryTimer) settingsRetryTimer = setInterval(refreshSettings, 20000);
                return;
            }
            if (settingsRetryTimer) { clearInterval(settingsRetryTimer); settingsRetryTimer = null; }
            el('eidli-settings-error').innerHTML = '';
            lastSettings = res.body.data;
            try { sessionStorage.setItem('eidli_cache_settings', JSON.stringify(lastSettings)); } catch (e) {}
            renderThresholdsAndMode();
            renderChart();
        }).catch(function () {
            el('eidli-settings-error').innerHTML = '<div class="eidli-section-error">Couldn\'t load settings — will retry.</div>';
            if (!settingsRetryTimer) settingsRetryTimer = setInterval(refreshSettings, 20000);
        });
    }

    // --- temperature chart -----------------------------------------------------
    //
    // Live-only: always today's telemetry, no date-range picker. The
    // confirmed backend contract has no server-side date-range params on
    // /temperature-logs, so this pages backward — newest first, same order
    // every other list endpoint here uses. Today's upper bound is always
    // "now", so it always starts sampling from offset 0 — no binary search
    // needed to locate a start offset (that machinery only mattered for
    // ranges whose upper bound was in the past, which no longer exist here).

    var IST_TZ_LOCAL = 'Asia/Kolkata';
    function fmtHM(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleTimeString('en-IN', { timeZone: IST_TZ_LOCAL, hour: '2-digit', minute: '2-digit', hour12: true });
    }
    function fmtDMY(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-IN', { timeZone: IST_TZ_LOCAL, day: '2-digit', month: 'short', year: 'numeric' });
    }

    // X-axis label format: time only — the chart only ever shows today's
    // live trend now, so a date component would be redundant on every point.
    function chartLabelFor(iso) {
        return fmtHM(iso);
    }

    // The chart is nudged forward a point on every ~2s tick of
    // refreshLiveTemperature() (see that function, above renderStatusGrid)
    // using the exact same temperature-logs record driving the hero/grid
    // number — never from /status. The 20s full refetch below stays as the
    // source of truth and replaces chartItems wholesale on its next tick, so
    // these interim points never accumulate unboundedly or drift from what
    // the backend actually has.

    // Stable Y-axis bounds, recomputed from the REAL data (every plotted
    // reading + both threshold lines — never an invented number) but
    // rounded outward to the nearest Y_AXIS_STEP so a tiny/expected
    // fluctuation near an already-comfortable margin doesn't move the axis
    // at all. Without this, Chart.js's default behavior is to autofit the
    // y-axis tightly to whatever's in the dataset on EVERY update() call —
    // so every ~2s live-nudge (which only ever appends one new point, see
    // refreshLiveTemperature) could shift the axis by a fraction of a
    // degree, which reads as the whole plotted line visually jumping/
    // rescaling even though no underlying value changed. Padding + rounding
    // means the axis only actually moves when a real reading approaches or
    // crosses the current rounded edge — a genuine large swing (heater
    // cycling, a real spike) still visibly expands the axis; it's the
    // sub-degree sensor jitter on an otherwise-stable reading that no
    // longer causes a visible rescale.
    var Y_AXIS_STEP = 5; // °C — matches the chart's own y-axis label granularity
    var Y_AXIS_PAD = 3; // °C headroom beyond the real min/max before rounding
    function computeStableYBounds(temps) {
        var values = temps.slice();
        if (lastSettings && lastSettings.off_temperature != null) values.push(Number(lastSettings.off_temperature));
        if (lastSettings && lastSettings.on_temperature != null) values.push(Number(lastSettings.on_temperature));
        values = values.filter(function (v) { return !isNaN(v); });
        if (!values.length) return null;
        var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
        return {
            min: Math.floor((min - Y_AXIS_PAD) / Y_AXIS_STEP) * Y_AXIS_STEP,
            max: Math.ceil((max + Y_AXIS_PAD) / Y_AXIS_STEP) * Y_AXIS_STEP
        };
    }

    function renderChart() {
        var items = chartItems;
        el('eidli-temp-chart-empty').style.display = items.length ? 'none' : 'block';
        if (!items.length) { if (tempChart) { tempChart.destroy(); tempChart = null; } return; }
        if (typeof Chart === 'undefined') return;

        var labels = items.map(function (r) { return chartLabelFor(r.recorded_at); });
        var temps = items.map(function (r) { return Number(r.temperature); });
        var yBounds = computeStableYBounds(temps);
        // Each point here is either a single live reading (the chart's
        // tail — see refreshLiveTemperature) or the mean of a contiguous
        // slice of real readings (the backfill on load/refresh — see
        // aggregateSlice in sampleRange). Never fabricated/interpolated.
        // tension: 0 draws straight segments between points rather than a
        // curved spline — a spline can overshoot past the actual plotted
        // values between points, which would misrepresent real data no
        // aggregation choice should paper over.
        var datasets = [{ label: 'Temperature (°C)', data: temps, borderColor: '#ff8a3d', backgroundColor: 'rgba(255,138,61,.12)', borderWidth: 2, pointRadius: 0, tension: 0, fill: true }];
        if (lastSettings && lastSettings.off_temperature != null) {
            datasets.push({ label: 'Heater Off (' + Number(lastSettings.off_temperature).toFixed(1) + '°C)', data: temps.map(function () { return Number(lastSettings.off_temperature); }), borderColor: '#f04747', borderDash: [6, 4], borderWidth: 1, pointRadius: 0, fill: false });
        }
        if (lastSettings && lastSettings.on_temperature != null) {
            datasets.push({ label: 'Heater Restart (' + Number(lastSettings.on_temperature).toFixed(1) + '°C)', data: temps.map(function () { return Number(lastSettings.on_temperature); }), borderColor: '#4098ff', borderDash: [6, 4], borderWidth: 1, pointRadius: 0, fill: false });
        }
        // Update the existing Chart.js instance in place rather than
        // destroy()/recreate on every 20s auto-refresh — avoids the visible
        // teardown/redraw flash. The tooltip callback below (defined once,
        // at initial creation) reads from the persistent chartItems module
        // var rather than a closed-over local, so it stays correct across
        // every subsequent update() even though it's never redefined.
        if (tempChart) {
            tempChart.data.labels = labels;
            tempChart.data.datasets = datasets;
            if (yBounds) {
                tempChart.options.scales.y.suggestedMin = yBounds.min;
                tempChart.options.scales.y.suggestedMax = yBounds.max;
            }
            tempChart.update('none');
            return;
        }

        var INK = '#a7b1bf', GRID = '#2c3644';
        tempChart = new Chart(el('eidli-temp-chart'), {
            type: 'line', data: { labels: labels, datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: {
                    legend: { display: true, labels: { color: INK, boxWidth: 12, font: { size: 11 } } },
                    tooltip: {
                        callbacks: {
                            title: function () { return ''; },
                            // Temperature / Date / Time on separate lines for the
                            // main series; threshold lines just show their label.
                            label: function (ctx) {
                                if (ctx.dataset.label !== 'Temperature (°C)') return ctx.dataset.label;
                                var r = chartItems[ctx.dataIndex];
                                if (!r) return '';
                                return [fmtTemp(r.temperature), fmtDMY(r.recorded_at), fmtHM(r.recorded_at)];
                            }
                        }
                    }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: INK, maxTicksLimit: 8, font: { size: 10 } } },
                    y: {
                        grid: { color: GRID }, ticks: { color: INK, callback: function (v) { return v + '°C'; } },
                        // suggestedMin/Max (not a hard min/max) — a real
                        // reading outside this padded band still expands
                        // the axis to show it rather than clipping/hiding
                        // it; see computeStableYBounds() above for why this
                        // exists and how it's kept real-data-driven.
                        suggestedMin: yBounds ? yBounds.min : undefined,
                        suggestedMax: yBounds ? yBounds.max : undefined
                    }
                }
            }
        });
    }

    // Today's bounds, always anchored to Asia/Kolkata (via core.js's
    // istDateISO()) regardless of the viewer's own timezone — the machine
    // is fixed in India even if an operator checks in from elsewhere.
    // Explicit "+05:30" suffix so this parses as an IST instant, not a
    // local-to-the-browser one.
    function computeTodayBounds() {
        var now = new Date();
        var todayIso = E.istDateISO(now);
        return { from: new Date(todayIso + 'T00:00:00+05:30').getTime(), to: now.getTime() };
    }

    // silent=true is for the 20s background auto-refresh of an
    // already-rendered chart: skip the "Loading…" indicator so nothing
    // visibly flashes while the chart quietly stays exactly as it is until
    // fresh data actually replaces it. Explicit refreshes (initial load, the
    // Refresh button) still show it — those are deliberate actions where
    // feedback is expected/useful.
    //
    // Returns a Promise<boolean> (true = chart actually updated with fresh
    // data, false = failed or skipped) that resolves only once finish() has
    // run and renderChart() has returned.
    // This backend does drop off the network briefly from time to time
    // (confirmed — see finish()'s comment below). Loading today's data is a
    // CHAIN of several requests (a probe for the total, then possibly many
    // page fetches) — without this, a single transient hiccup ANYWHERE in
    // that chain aborted the whole attempt and reported failure via the
    // toast, even when the chart on screen (from a still-good earlier load)
    // was perfectly fine. This retries up to twice per request (3 attempts
    // total) with backoff, instead of just once — absorbing this instead of
    // surfacing it to the operator as a confusing "failed" toast next to a
    // chart that's clearly showing data.
    function apiFetchRetry(url, attempt) {
        attempt = attempt || 0;
        function retry() {
            if (attempt >= 2) return apiFetch(url); // final attempt — let the caller's own ok/success check handle a real, persistent failure
            return new Promise(function (r) { setTimeout(r, 400 * (attempt + 1)); }).then(function () { return apiFetchRetry(url, attempt + 1); });
        }
        return apiFetch(url).then(function (res) {
            return (res.ok && res.body.success) ? res : retry();
        }).catch(retry);
    }

    function fetchChartData(silent) {
        var fetchFromTs = rangeFromTs;
        var fetchToTs = rangeToTs;
        return new Promise(function (resolve) {
            if (!CONFIGURED) { resolve(false); return; }
            if (chartFetchInFlight) {
                // A newer request arrived while one was already running —
                // note that a refresh is still owed, and once the in-flight
                // one settles, one more fetch runs for whatever "today"
                // bounds are current AT THAT POINT.
                pendingChartRefresh = true;
                resolve(false);
                return;
            }
            chartFetchInFlight = true;
            // Starting a fresh attempt always clears both prior outcomes, so a
            // stale "no data" can never linger alongside a new error (or the
            // loading state).
            el('eidli-temp-chart-error').style.display = 'none';
            el('eidli-temp-chart-empty').style.display = 'none';
            if (!silent) {
                var loadingText = el('eidli-temp-chart-loading-text');
                if (loadingText) loadingText.textContent = 'Loading…';
                el('eidli-temp-chart-loading').style.display = 'flex';
            }

            function finish(items, failed) {
                chartFetchInFlight = false;
                el('eidli-temp-chart-loading').style.display = 'none';
                if (failed) {
                    el('eidli-temp-chart-error').style.display = 'block';
                    // Deliberately do NOT touch chartItems/renderChart() here —
                    // a transient fetch failure (this backend does drop off the
                    // network briefly from time to time) must never blank out a
                    // chart that's already successfully on screen. The error
                    // banner surfaces the problem without discarding good data.
                    resolve(false);
                    runPendingChartRefresh();
                    return;
                }
                items = items.slice().sort(function (a, b) { return new Date(a.recorded_at) - new Date(b.recorded_at); });
                items = items.filter(function (r) {
                    var t = new Date(r.recorded_at).getTime();
                    return t >= fetchFromTs && t <= fetchToTs;
                });
                chartItems = items;
                renderChart();
                resolve(true);
                runPendingChartRefresh();
            }

            var rangeQuery = '&start_time=' + encodeURIComponent(new Date(fetchFromTs).toISOString()) +
                '&end_time=' + encodeURIComponent(new Date(fetchToTs).toISOString());
            function temperatureLogsUrl(offset) {
                return URLS.temperatureLogs + '?limit=1&offset=' + offset + rangeQuery;
            }

            // Runs up to `limit` of these concurrently rather than firing
            // all of them via a bare Promise.all: confirmed by direct
            // measurement that the machine backend can't sustain very high
            // request concurrency (100/160 single-row reads failed outright
            // in one measured burst), and an uncapped burst also
            // monopolizes the browser's per-origin connection queue for the
            // entire duration it takes to drain. Capping leaves connection
            // headroom so smaller, time-sensitive requests on this same
            // page — chiefly the live temperature poll
            // (refreshLiveTemperature) — keep getting through promptly the
            // whole time this runs. (CHART_FETCH_CONCURRENCY itself is
            // defined further below, next to the values it was actually
            // tuned alongside.)
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

            // The number of rows fetched per sampled window. Deliberately
            // NOT the backend's max (/temperature-logs caps `limit` at 500,
            // confirmed via its OpenAPI schema) — measured directly
            // against this backend: per-request latency scales with rows
            // requested (500 rows ~700ms-3s+, 50 rows ~150-300ms in
            // isolation), AND concurrent requests contend with each other
            // server-side regardless of size (fewer, larger concurrent
            // requests were NOT faster overall — tested). A 50-row window
            // is still plenty for aggregateSlice below to average out
            // sensor jitter, and fetching many small windows (one per
            // sampled point-cluster, spread evenly across the whole range)
            // keeps the SAME temporal coverage as before instead of
            // sampling only a handful of widely-separated windows — that
            // was tried first and rejected: it left large unsampled gaps
            // that rendered as sharp artificial-looking jumps between
            // clusters, which misrepresents the data far more than the
            // point-to-point jitter this whole aggregation approach exists
            // to fix in the first place.
            var CHART_SAMPLE_SIZE = 50;
            function temperaturePageUrl(pageOffset) {
                return URLS.temperatureLogs + '?limit=' + CHART_SAMPLE_SIZE + '&offset=' + pageOffset + rangeQuery;
            }

            // Points to pull out of each fetched window, evenly spaced
            // within it. Combined with the window count below, this bounds
            // the TOTAL number of requests to roughly
            // CHART_MAX_POINTS / POINTS_PER_WINDOW regardless of how large
            // today's total record count is.
            var POINTS_PER_WINDOW = 8;
            // Concurrency is deliberately low (measured: 2-3 concurrent
            // requests completed a full load in ~2-3s; 6-10 concurrent made
            // the SAME workload slower, 4-6s+ — this backend appears to
            // serialize/contend on concurrent requests rather than
            // benefiting from more parallelism).
            var CHART_FETCH_CONCURRENCY = 3;

            // Each chart point is the MEAN of a contiguous slice of real
            // backend readings, not a single cherry-picked row — this
            // sensor reports noisy/near-duplicate values in rapid
            // succession (confirmed: consecutive raw readings a couple
            // seconds apart routinely differ by 0.25-0.5°C purely from
            // sensor noise, not an actual temperature change), so picking
            // one arbitrary row per slice produced a visibly jagged line
            // even though every individual point was technically real. A
            // slice's average is still built entirely from real readings —
            // it summarizes what actually happened across that
            // sub-interval instead of showing one arbitrary instant of it,
            // which is what a temperature TREND is meant to show. This is
            // a genuine statistical aggregate, not smoothing/interpolation:
            // no value is invented, and a real spike/drop that dominates a
            // slice still shows up in that slice's average - only pure
            // point-to-point sensor jitter gets absorbed. recorded_at is
            // the slice's middle reading's real timestamp.
            function aggregateSlice(rows) {
                var sum = 0, count = 0;
                for (var i = 0; i < rows.length; i++) {
                    var t = Number(rows[i].temperature);
                    if (!isNaN(t)) { sum += t; count++; }
                }
                if (!count) return null;
                return { temperature: sum / count, recorded_at: rows[Math.floor(rows.length / 2)].recorded_at };
            }

            function sampleRange(total) {
                var startOffset = 0, lastOffset = total - 1;
                var span = lastOffset - startOffset + 1;
                var count = Math.min(CHART_MAX_POINTS, span);
                var pageCount = Math.max(1, Math.min(Math.ceil(count / POINTS_PER_WINDOW), Math.ceil(span / CHART_SAMPLE_SIZE)));
                // Each window-start is clamped so pageStart..pageStart+CHART_SAMPLE_SIZE-1
                // stays within [startOffset, lastOffset] where possible, so a
                // fetched window isn't mostly wasted hanging off the range's edge.
                var maxPageStart = Math.max(startOffset, lastOffset - CHART_SAMPLE_SIZE + 1);
                var pageStarts = [];
                for (var p = 0; p < pageCount; p++) {
                    pageStarts.push(Math.round(startOffset + (maxPageStart - startOffset) * p / Math.max(1, pageCount - 1)));
                }
                var pointsPerThisPage = Math.max(1, Math.round(count / pageCount));
                runLimited(pageStarts, CHART_FETCH_CONCURRENCY, function (pageStart) {
                    return apiFetchRetry(temperaturePageUrl(pageStart)).then(function (res) {
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
                    }).catch(function () { return []; });
                }).then(function (perPageResults) {
                    var readings = [].concat.apply([], perPageResults).filter(Boolean);
                    finish(readings, readings.length === 0);
                }).catch(function () { finish([], true); });
            }

            apiFetchRetry(temperatureLogsUrl(0)).then(function (res) {
                if (!res.ok || !res.body.success) { finish([], true); return; }
                var total = (res.body.data && res.body.data.total) || 0;
                if (!total) { finish([], false); return; }
                sampleRange(total);
            }).catch(function () {
                finish([], true);
            });
        });
    }

    // Cache-first isn't needed anymore now there's only ever one range
    // (today) — a normal (non-silent) fetch each time this is called.
    function applyRangeCore() {
        return fetchChartData().then(function (ok) { return ok; });
    }


    // --- wiring -----------------------------------------------------------------

    function bindControls() {
        // blur() once the fetch settles removes the focus ring Bootstrap
        // leaves on the button after a click, rather than leaving it
        // visibly "stuck" highlighted.
        el('eidli-temp-refresh').addEventListener('click', function () {
            var btn = this;
            fetchChartData().then(function () { btn.blur(); });
        });
    }

    // Paints the last-known status/session/settings the instant the page
    // opens, straight from sessionStorage — zero network wait. This is what
    // makes Dashboard -> History -> Dashboard show real values immediately
    // instead of placeholders: the live fetches below still run exactly as
    // before and silently replace these with fresh data moments later.
    // First-ever visit in a tab has nothing cached yet, so it still shows
    // placeholders until the first real response — unavoidable, there's
    // nothing to show before any data has ever arrived.
    function hydrateFromCache() {
        try {
            var s = sessionStorage.getItem('eidli_cache_status');
            if (s !== null) renderStatusGrid(JSON.parse(s));
        } catch (e) {}
        try {
            var lt = sessionStorage.getItem('eidli_cache_live_temp');
            if (lt !== null) {
                lastLiveTemp = JSON.parse(lt);
                lastLiveTempMs = new Date(lastLiveTemp.recorded_at).getTime();
                if (isNaN(lastLiveTempMs)) { lastLiveTemp = null; lastLiveTempMs = null; }
                else renderTempDisplay();
            }
        } catch (e) {}
        try {
            var set = sessionStorage.getItem('eidli_cache_settings');
            if (set !== null) { lastSettings = JSON.parse(set); renderThresholdsAndMode(); }
        } catch (e) {}
    }

    document.addEventListener('DOMContentLoaded', function () {
        bindControls();
        E.startHeader();
        renderFaultBanner(null);
        if (!CONFIGURED) {
            el('eidli-settings-error').innerHTML = '<div class="eidli-section-empty">Not connected.</div>';
            return;
        }

        hydrateFromCache();

        E.onStatus(function () {
            if (firstLiveStatusLogged) return;
            firstLiveStatusLogged = true;
            console.debug('[dashboard-timing] first live temperature/heater/machine/sensor status displayed at', performance.now().toFixed(0), 'ms since navigation start');
        });
        E.onStatus(renderStatusGrid);
        refreshSettings();
        refreshLiveTemperature();
        setInterval(function () {
            if (document.visibilityState !== 'visible') return;
            refreshLiveTemperature();
        }, LIVE_TEMP_POLL_MS);
        // Initial chart load — today's data should be visible immediately
        // on open, not gated behind any control.
        var bounds = computeTodayBounds();
        rangeFromTs = bounds.from; rangeToTs = bounds.to;
        applyRangeCore();

        setInterval(function () {
            if (document.visibilityState !== 'visible') return;
            // silent=true: this is a background refresh of an
            // already-rendered chart, not a user-initiated one — no
            // "Loading…" flash, no visible disruption if nothing changed.
            if (!chartFetchInFlight) {
                var b = computeTodayBounds();
                rangeFromTs = b.from; rangeToTs = b.to;
                fetchChartData(true);
            }
        }, 20000);
    });
})();
