/*
 * Electric Idli Machine — Dashboard page.
 *
 * Live-update strategy:
 *   - /status polled every 3s, owned by core.js's shared header loop —
 *     this page just subscribes via Eidli.onStatus() instead of opening a
 *     second interval against the same endpoint. Drives the live
 *     temperature number (status grid + hero) *and*, when the temperature
 *     chart's Today filter is active, nudges the chart forward a point
 *     every tick too (pushLiveTemperaturePoint) — same poll, no extra
 *     request.
 *   - current session + heating cycles + recent events polled every 20s.
 *     Recent events here is a `limit=5` fetch (not the full log), so —
 *     unlike the old full Cooking History table — polling it on a timer is
 *     cheap regardless of how many thousands of rows exist backend-side.
 *     The temperature chart also gets a full authoritative re-fetch on this
 *     same 20s tick, but only while its Today filter is selected —
 *     historical ranges are static, fetched on selection/refresh only.
 *   - settings + session-summary totals: on load + manual refresh only.
 */
(function () {
    var E = window.Eidli;
    var el = E.el, esc = E.esc, apiFetch = E.apiFetch, errMsg = E.errMsg;
    var fmtTemp = E.fmtTemp, fmtTime = E.fmtTime, fmtDuration = E.fmtDuration, fmtRelative = E.fmtRelative;
    var URLS = E.URLS, CONFIGURED = E.CONFIGURED;

    var lastSettings = null;
    var lastCycles = [];
    var currentSession = null;
    var tempChart = null;
    var chartItems = [];
    var chartFetchInFlight = false;
    var currentRange = 'today'; // the APPLIED range — only changes when Apply actually runs
    var pendingRangePreset = 'today'; // which quick-range button is highlighted; can differ from currentRange until Apply is clicked
    var rangeFromTs = null, rangeToTs = null;
    var customMultiDay = false;
    var chartApplyInFlight = false;
    // Per-range readings cache (Custom excluded — its bounds are arbitrary,
    // not worth key-caching) so re-selecting a range already loaded this
    // page-session paints instantly while a background refetch keeps it
    // current, instead of re-running the whole fetch pipeline from scratch
    // every single time. Purely in-memory — resets on a real page reload,
    // same as chartItems itself.
    var chartRangeCache = {};
    var CACHEABLE_RANGES = ['today', 'yesterday', '7days', '30days'];
    // Set when a fetchChartData() call arrives while another is already in
    // flight — instead of just dropping it, one more fetch runs once the
    // in-flight one settles, targeting whatever range is current AT THAT
    // POINT. Rapidly clicking through several ranges this way converges on
    // the last one the user actually landed on, without queuing a fetch
    // per click.
    var pendingChartRefresh = false;
    function runPendingChartRefresh() {
        if (pendingChartRefresh) { pendingChartRefresh = false; fetchChartData(true); }
    }
    var CHART_PAGE = 500; // the backend's /temperature-logs caps `limit` at 500 (confirmed via its live OpenAPI schema: maximum=500) — a higher value 422s
    var CHART_MAX_POINTS = 160; // actual backend records; no averaging or conversion
    var commandInFlight = false;
    var sessionActionInFlight = false;
    var modeSwitchInFlight = false;
    var heaterToggleInFlight = false;
    var heaterDesiredState = null;
    var heaterCommandHoldUntil = 0;
    var HEATER_STATUS_GRACE_MS = 10000;
    var lastSessionControlsKey; // undefined until first render — see renderSessionMini
    var sessionFetchSeq = 0;
    var elapsedTimer = null;
    // One-shot flags for the requested initial-load timing instrumentation
    // (temporary, per the investigation ask — safe to remove once load time
    // is confirmed fixed). Guards against re-logging on every subsequent
    // live poll, only the FIRST live response after page open matters here.
    var firstLiveSessionLogged = false;
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
        var temp = status.current_temperature;
        if (temp !== undefined && temp !== null && temp !== '') {
            el('eidli-grid-temp').textContent = fmtTemp(temp);
            el('eidli-temp-hero').textContent = fmtTemp(temp);
            el('eidli-temp-hero-sub').textContent = status.is_online ? 'Current temperature' : 'Last known temperature (machine offline)';
        } else {
            el('eidli-grid-temp').textContent = '—';
            el('eidli-temp-hero').textContent = '—';
            el('eidli-temp-hero-sub').textContent = 'No reading available';
        }
        el('eidli-grid-machine').innerHTML = E.machineStateBadge(status.machine_status);
        el('eidli-grid-heater').innerHTML = E.heaterBadge(status.heater_status);
        el('eidli-grid-sensor').innerHTML = E.sensorBadge(status.sensor_status);
        renderFaultBanner(status);
        updateControlsDisabled(status);
        updateHeaterToggleState(status);
    }

    // The heater toggle reflects the machine's confirmed heater_status from
    // /status (the same 3s-polled telemetry driving the live temperature
    // number and the "Heater" badge) — this is what corrects the switch to
    // the machine's real state within a few seconds even after the
    // optimistic flip toggleHeater() does on click (see below), and what
    // restores it if a command fails. Skipped while a toggle request is
    // still in flight so the poll can't visually fight the user's
    // just-clicked position before the request resolves.
    function updateHeaterToggleState(status) {
        var toggle = el('eidli-heater-toggle');
        if (!toggle || heaterToggleInFlight) return;
        var heaterStatus = ((status && status.heater_status) || '').toLowerCase();
        var confirmedOn = heaterStatus === 'on';
        if (heaterDesiredState !== null) {
            if (confirmedOn === heaterDesiredState) {
                heaterDesiredState = null;
                heaterCommandHoldUntil = 0;
            } else if (Date.now() < heaterCommandHoldUntil) {
                toggle.checked = heaterDesiredState;
                return;
            }
        }
        toggle.checked = confirmedOn;
    }

    function updateControlsDisabled(status) {
        var online = !!(status && status.is_online);
        var disabled = !CONFIGURED || !online || commandInFlight;
        var b = el('eidli-restart-btn'); if (b) b.disabled = disabled;
        var heaterToggle = el('eidli-heater-toggle');
        if (heaterToggle) heaterToggle.disabled = !CONFIGURED || !online || heaterToggleInFlight;
        var startBtn = el('eidli-session-start-btn');
        if (startBtn && !currentSession) startBtn.disabled = !CONFIGURED || !online || sessionActionInFlight;
        var toggle = document.querySelectorAll('#eidli-mode-toggle button');
        toggle.forEach(function (b) { b.disabled = !CONFIGURED || !online || modeSwitchInFlight; });
    }

    // --- settings-derived: thresholds + mode ---------------------------------

    function renderThresholdsAndMode() {
        if (!lastSettings) return;
        el('eidli-threshold-off').textContent = fmtTemp(lastSettings.off_temperature);
        el('eidli-threshold-restart').textContent = fmtTemp(lastSettings.on_temperature);

        var mode = (lastSettings.mode || '').toLowerCase();
        el('eidli-grid-mode').innerHTML = E.modeBadge(mode);
        document.querySelectorAll('#eidli-mode-toggle button').forEach(function (b) {
            var isActive = b.getAttribute('data-mode') === mode;
            b.classList.toggle('active', isActive);
            b.setAttribute('aria-pressed', String(isActive));
        });
        el('eidli-manual-controls').style.display = (mode === 'manual') ? 'block' : 'none';
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

    function switchMode(newMode) {
        if (modeSwitchInFlight || !lastSettings || lastSettings.mode === newMode) return;
        var label = newMode === 'auto' ? 'Automatic' : 'Manual';
        var fromLabel = lastSettings.mode === 'auto' ? 'Automatic' : 'Manual';
        if (!confirm('Switch operating mode?\n\n' + fromLabel + ' → ' + label)) return;
        modeSwitchInFlight = true;
        updateControlsDisabled(E.getLastStatus());
        apiFetch(URLS.settings, { method: 'PATCH', body: JSON.stringify({ mode: newMode }) }).then(function (res) {
            modeSwitchInFlight = false;
            if (res.ok && res.body.success) {
                lastSettings = res.body.data;
                renderThresholdsAndMode();
                window.showToast('success', 'Operating mode switched to ' + label + '.');
            } else {
                window.showToast('danger', 'Failed to switch mode: ' + errMsg(res, 'unknown error'));
            }
            updateControlsDisabled(E.getLastStatus());
        }).catch(function () {
            modeSwitchInFlight = false;
            updateControlsDisabled(E.getLastStatus());
            window.showToast('danger', 'Failed to switch mode: network error.');
        });
    }

    // --- current cooking session ----------------------------------------------

    function stopElapsedTimer() { if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; } }

    function startElapsedTimer(startedAt) {
        stopElapsedTimer();
        var start = new Date(startedAt).getTime();
        if (isNaN(start)) return;
        function tick() {
            var e = el('eidli-session-elapsed');
            if (!e) { stopElapsedTimer(); return; }
            e.textContent = fmtDuration(Math.max(0, Math.floor((Date.now() - start) / 1000)));
        }
        tick();
        elapsedTimer = setInterval(tick, 1000);
    }

    // mini's own innerHTML (text only, no listeners) is cheap to rebuild on
    // every call and always kept fresh. controls' innerHTML carries the
    // Start/Complete button and its click listener — now that this fires
    // every ~3s (piggybacking on the shared status poll) instead of every
    // 20s, rebuilding it unconditionally would tear down and re-attach that
    // listener 6-7x more often than before for no reason, and could drop
    // keyboard focus mid-interaction. It's skipped whenever the session's
    // identity + active/inactive state haven't actually changed since the
    // last render — the only two things that determine which button shows.
    function renderSessionMini(session) {
        // Cached (including the explicit "no active session" case) for the
        // same instant-hydration-on-reopen purpose as cacheStatus() above.
        try { sessionStorage.setItem('eidli_cache_session', JSON.stringify(session)); } catch (e) {}
        var mini = el('eidli-session-mini');
        var controls = el('eidli-session-controls');

        if (!session) {
            mini.innerHTML = '<div class="text-muted small">No active cooking session.</div>';
            if (lastSessionControlsKey === 'none') return;
            lastSessionControlsKey = 'none';
            stopElapsedTimer();
            controls.innerHTML = '<button type="button" class="btn btn-success" id="eidli-session-start-btn"' +
                (CONFIGURED && E.getLastStatus() && E.getLastStatus().is_online ? '' : ' disabled') + '>' +
                '<i class="ri-play-circle-line icon-sm me-1"></i>Start Cooking Session</button>';
            var startBtn = el('eidli-session-start-btn');
            if (startBtn) startBtn.addEventListener('click', startSession);
            return;
        }

        var isActive = (session.status || '').toLowerCase() === 'active';
        var html = '<div class="mb-1"><strong>Session #' + esc(session.session_number) + '</strong> ' + E.sessionStatusBadge(session.status) + '</div>';
        html += '<div class="small text-muted">Started ' + esc(E.fmtTime(session.started_at)) + '</div>';
        if (isActive) {
            html += '<div class="small">Elapsed: <strong id="eidli-session-elapsed">—</strong></div>';
        } else if (session.completed_at) {
            html += '<div class="small text-muted">Ended ' + esc(E.fmtTime(session.completed_at)) + ' (' + fmtDuration(session.duration_seconds) + ')</div>';
        }
        html += '<div class="small">Cycles: <strong>' + (session.heating_cycle_count != null ? session.heating_cycle_count : '—') + '</strong> · Max: <strong>' + fmtTemp(session.max_temperature) + '</strong></div>';
        if (session.end_reason) html += '<div class="small" style="color:var(--eidli-bad);"><i class="ri-alert-line icon-sm"></i> ' + esc(session.end_reason) + '</div>';
        mini.innerHTML = html;

        // The elapsed-time <strong> above just got a fresh DOM node from the
        // innerHTML swap, but startElapsedTimer's ticker looks it up by id
        // fresh on every 1s tick (not a cached reference), so it keeps
        // updating the new node transparently — no need to restart it here.
        var key = session.id + '|' + isActive;
        if (key === lastSessionControlsKey) return;
        lastSessionControlsKey = key;
        stopElapsedTimer();

        if (isActive) {
            startElapsedTimer(session.started_at);
            controls.innerHTML = '<button type="button" class="btn btn-success" id="eidli-session-complete-btn">Complete Session</button>';
            el('eidli-session-complete-btn').addEventListener('click', function () { completeSession(session.id); });
        } else {
            controls.innerHTML = '<button type="button" class="btn btn-success" id="eidli-session-start-btn"' +
                (CONFIGURED && E.getLastStatus() && E.getLastStatus().is_online ? '' : ' disabled') + '>' +
                '<i class="ri-play-circle-line icon-sm me-1"></i>Start Cooking Session</button>';
            var startBtn2 = el('eidli-session-start-btn');
            if (startBtn2) startBtn2.addEventListener('click', startSession);
        }
    }

    // Now called every ~3s (piggybacking on the shared status poll) instead
    // of every 20s — the sequence guard makes sure a slow response can't
    // land after (and overwrite with stale data) a faster, more recent one.
    function refreshSession() {
        if (!CONFIGURED) return;
        var seq = ++sessionFetchSeq;
        apiFetch(URLS.sessionCurrent).then(function (res) {
            if (seq !== sessionFetchSeq) return;
            if (!res.ok || !res.body.success) {
                el('eidli-session-mini').innerHTML = '<div class="eidli-section-error">Unable to load session status.</div>';
                return;
            }
            currentSession = res.body.data || null;
            renderSessionMini(currentSession);
            renderTodayStrip();
            if (!firstLiveSessionLogged) {
                firstLiveSessionLogged = true;
                console.debug('[dashboard-timing] first live session displayed at', performance.now().toFixed(0), 'ms since navigation start');
            }
        }).catch(function () {
            if (seq !== sessionFetchSeq) return;
            el('eidli-session-mini').innerHTML = '<div class="eidli-section-error">Unable to load session status.</div>';
        });
    }

    function startSession() {
        if (sessionActionInFlight) return;
        if (!confirm('Start a new cooking session on this machine?')) return;
        sessionActionInFlight = true;
        apiFetch(URLS.sessionStart, { method: 'POST' }).then(function (res) {
            sessionActionInFlight = false;
            if (res.ok && res.body.success) window.showToast('success', 'Cooking session started.');
            else if (res.status === 409) window.showToast('danger', errMsg(res, 'A cooking session is already active.'));
            else window.showToast('danger', 'Failed to start session: ' + errMsg(res, 'unknown error'));
            refreshSession(); refreshCycles(); refreshRecentEvents();
        }).catch(function () {
            sessionActionInFlight = false;
            window.showToast('danger', 'Failed to start session: network error.');
        });
    }

    function completeSession(sessionId) {
        if (sessionActionInFlight) return;
        if (!confirm('Complete this cooking session?\n\nThis will mark the cooking session as completed.')) return;
        sessionActionInFlight = true;
        apiFetch(URLS.sessionCompleteTpl.replace('__ID__', sessionId), { method: 'POST' }).then(function (res) {
            sessionActionInFlight = false;
            if (res.ok && res.body.success) window.showToast('success', 'Cooking session completed.');
            else window.showToast('danger', 'Failed to complete session: ' + errMsg(res, 'unknown error'));
            refreshSession(); refreshCycles(); refreshRecentEvents();
        }).catch(function () {
            sessionActionInFlight = false;
            window.showToast('danger', 'Failed to complete session: network error.');
        });
    }

    // --- temperature chart -----------------------------------------------------
    //
    // Date-range filter: Today (default, live — re-fetched by the 20s poll
    // below) / Yesterday / Last 7 Days / Last 30 Days / Custom. The confirmed
    // backend contract has no server-side date-range params on
    // /temperature-logs, so this pages backward — newest first, same order
    // every other list endpoint here uses — via a binary search that jumps
    // straight to the offset where the range's upper bound starts (this
    // backend logs roughly once a second, so "everything newer than
    // yesterday" alone is already ~30,000 rows — walking there one page at a
    // time would be far too slow). Ranges that extend through "now" (Today,
    // 7/30 days, a Custom range ending today) skip the search entirely since
    // offset 0 already satisfies the upper bound.

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
    function fmtDMHM(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-IN', { timeZone: IST_TZ_LOCAL, day: '2-digit', month: 'short' }) + ', ' + fmtHM(iso);
    }

    // X-axis label format per the selected range, per spec: Today/Yesterday
    // -> time only; Last 7 Days -> date+time; Last 30 Days -> date only;
    // Custom -> date+time if it spans more than one day, else time only.
    function chartLabelFor(iso) {
        // Today/Yesterday -> hours; Last 7/30 Days -> dates (both date-only
        // now, not date+time — a 7-day chart has far too many points for
        // per-point time to be legible anyway, and this matches Last 30
        // Days' existing treatment for consistency between the two
        // multi-day presets). Custom -> date+time if it spans more than one
        // day, else time only, since a custom range's span is arbitrary.
        if (currentRange === '30days' || currentRange === '7days') return fmtDMY(iso);
        if (currentRange === 'custom') return customMultiDay ? fmtDMHM(iso) : fmtHM(iso);
        return fmtHM(iso); // today, yesterday
    }

    // Nudges the chart forward every 3s using the SAME /status poll already
    // driving the live temperature number (core.js's shared poll, via
    // Eidli.onStatus) — no extra network request, no new timer. Only
    // applies to the Today filter; historical ranges are static. The 20s
    // full refetch below stays as the source of truth and will replace
    // chartItems wholesale on its next tick, so these interim points never
    // accumulate unboundedly or drift from what the backend actually has.
    // Never append /status readings here: the chart must contain only
    // timestamped temperature-log records returned by the backend.

    function renderChart() {
        var items = chartItems;
        el('eidli-temp-chart-empty').style.display = items.length ? 'none' : 'block';
        if (!items.length) { if (tempChart) { tempChart.destroy(); tempChart = null; } return; }
        if (typeof Chart === 'undefined') return;

        var labels = items.map(function (r) { return chartLabelFor(r.recorded_at); });
        var temps = items.map(function (r) { return Number(r.temperature); });
        // Do not smooth or average readings; each point is a backend value.
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
                    y: { grid: { color: GRID }, ticks: { color: INK, callback: function (v) { return v + '°C'; } } }
                }
            }
        });
    }

    // Bounds for the four named presets, always anchored to Asia/Kolkata
    // (via core.js's istDateISO()) regardless of the viewer's own timezone —
    // the machine is fixed in India even if an operator checks in from
    // elsewhere. Explicit "+05:30" suffixes so these parse as IST instants,
    // not local-to-the-browser ones.
    function computeRangeBounds(range) {
        var now = new Date();
        var ONE_DAY_MS = 24 * 60 * 60 * 1000;
        var todayIso = E.istDateISO(now);
        if (range === 'today') {
            return { from: new Date(todayIso + 'T00:00:00+05:30').getTime(), to: now.getTime() };
        }
        if (range === 'yesterday') {
            var y = E.istDateISO(new Date(now.getTime() - ONE_DAY_MS));
            return { from: new Date(y + 'T00:00:00+05:30').getTime(), to: new Date(y + 'T23:59:59.999+05:30').getTime() };
        }
        if (range === '7days') {
            var from7 = E.istDateISO(new Date(now.getTime() - 6 * ONE_DAY_MS));
            return { from: new Date(from7 + 'T00:00:00+05:30').getTime(), to: now.getTime() };
        }
        if (range === '30days') {
            var from30 = E.istDateISO(new Date(now.getTime() - 29 * ONE_DAY_MS));
            return { from: new Date(from30 + 'T00:00:00+05:30').getTime(), to: now.getTime() };
        }
        return null;
    }

    // YYYY-MM-DD for a <input type=date> value, in IST calendar terms —
    // same convention istDateISO() already uses everywhere else here.
    function fmtDateInputValue(ts) {
        return E.istDateISO(new Date(ts));
    }

    // DD-MM-YYYY for the active-filter indicator's custom-range display.
    function fmtDMYNumeric(ts) {
        var parts = fmtDateInputValue(ts).split('-');
        return parts[2] + '-' + parts[1] + '-' + parts[0];
    }

    function highlightRangeButton(range) {
        document.querySelectorAll('#eidli-temp-range-group button').forEach(function (b) {
            var active = b.getAttribute('data-range') === range;
            b.classList.toggle('btn-success', active);
            b.classList.toggle('btn-outline-secondary', !active);
        });
    }

    var RANGE_LABELS = { today: 'Today', yesterday: 'Yesterday', '7days': 'Last 7 Days', '30days': 'Last 30 Days' };

    // Cache by the actual applied dates, not just a preset name. This keeps a
    // previous custom range from ever being reused for different From/To dates
    // and lets a range repaint immediately while its refresh stays silent.
    function chartRangeCacheKey(range, fromTs, toTs) {
        return range + ':' + fmtDateInputValue(fromTs) + ':' + fmtDateInputValue(toTs);
    }

    // Single source of truth for how the currently-APPLIED range (not the
    // merely-highlighted pendingRangePreset) reads as text — shared by the
    // persistent indicator, the transient confirmation, and the loading
    // overlay's "Loading X…" message, so all three can never disagree.
    function currentRangeDisplayLabel() {
        return (currentRange === 'custom')
            ? (fmtDMYNumeric(rangeFromTs) + ' → ' + fmtDMYNumeric(rangeToTs))
            : (RANGE_LABELS[currentRange] || currentRange);
    }

    // Always shows exactly what's currently applied to the chart — updated
    // only from applyDashboardRange(), never from selectRange() (which just
    // stages a pending selection), so this can never drift out of sync with
    // what's actually on screen.
    function updateActiveFilterIndicator() {
        var indicator = el('eidli-temp-active-filter');
        if (!indicator) return;
        indicator.innerHTML = 'Showing: <strong>' + esc(currentRangeDisplayLabel()) + '</strong>';
    }

    // Transient confirmation in the card HEADER (distinct from the
    // persistent indicator above) — only shown right after an Apply
    // actually changes what's displayed, so a filter change is impossible
    // to miss. Auto-hides itself after a few seconds; a later Apply clears
    // any still-pending hide timer so it can't disappear mid-display for a
    // brand new confirmation.
    var tempApplyConfirmTimer = null;
    function showTempApplyConfirmation() {
        var banner = el('eidli-temp-apply-confirm');
        if (!banner) return;
        banner.textContent = '✓ Showing ' + currentRangeDisplayLabel();
        banner.style.display = 'inline';
        if (tempApplyConfirmTimer) clearTimeout(tempApplyConfirmTimer);
        tempApplyConfirmTimer = setTimeout(function () { banner.style.display = 'none'; }, 4000);
    }

    // silent=true is for the 20s background auto-refresh of an already-
    // rendered Today chart: skip the "Loading…" indicator so nothing
    // visibly flashes while the chart quietly stays exactly as it is until
    // fresh data actually replaces it. Explicit refreshes (initial load,
    // the Refresh button, Apply) still show it — those are deliberate
    // actions where feedback is expected/useful.
    //
    // Returns a Promise<boolean> (true = chart actually updated with fresh
    // data, false = failed or skipped) that resolves only once finish() has
    // run and renderChart() has returned — callers (the Apply button) that
    // need to know when the chart is truly done, not just "request sent",
    // await this instead of guessing from a fire-and-forget call.
    // This backend does drop off the network briefly from time to time
    // (confirmed — see finish()'s comment below). Loading a historical
    // range is a CHAIN of several requests (a probe for the total, a
    // binary search across several more probes, then possibly HUNDREDS of
    // page fetches for a wide range like Last 7/30 Days — up to
    // CHART_MAX_PAGES of them) — without this, a single transient hiccup
    // ANYWHERE in that chain aborted the whole attempt and reported
    // failure via the toast, even when the chart on screen (from a still-
    // good earlier load) was perfectly fine. A longer chain has more
    // chances to hit a hiccup, so this retries up to twice per request
    // (3 attempts total) with backoff, instead of just once — absorbing
    // this instead of surfacing it to the operator as a confusing "failed"
    // toast next to a chart that's clearly showing data.
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
        // Snapshotted now, not read again inside finish() — if the user
        // switches to a DIFFERENT range while this fetch is still in
        // flight, currentRange will have moved on by the time this
        // resolves, and this stale fetch must not clobber the newer
        // range's display with old data.
        var fetchRange = currentRange;
        var fetchFromTs = rangeFromTs;
        var fetchToTs = rangeToTs;
        var fetchCacheKey = chartRangeCacheKey(fetchRange, fetchFromTs, fetchToTs);
        return new Promise(function (resolve) {
            if (!CONFIGURED) { resolve(false); return; }
            if (chartFetchInFlight) {
                // A newer request arrived while one was already running —
                // note that a refresh is still owed, and once the in-flight
                // one settles, fetch whatever range is current AT THAT
                // POINT (not this stale snapshot) — so rapidly clicking
                // through several ranges converges on the last one the
                // user actually landed on instead of queuing up a fetch
                // per click.
                pendingChartRefresh = true;
                resolve(false);
                return;
            }
            chartFetchInFlight = true;
            // Starting a fresh attempt always clears both prior outcomes, so a
            // stale "no data" from a previous range can never linger alongside
            // a new error (or the loading state).
            el('eidli-temp-chart-error').style.display = 'none';
            el('eidli-temp-chart-empty').style.display = 'none';
            if (!silent) {
                // currentRange/rangeFromTs/rangeToTs are already updated to
                // the NEW target range by the time applyDashboardRange()
                // calls this, so "Loading Yesterday…" etc. is accurate —
                // not whatever was displayed before this fetch started.
                var loadingText = el('eidli-temp-chart-loading-text');
                if (loadingText) loadingText.textContent = 'Loading ' + currentRangeDisplayLabel() + '…';
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
                // Only apply this to the chart if the user is still looking
                // at the range this fetch was actually for — see the
                // fetchRange snapshot above.
                if (fetchRange === currentRange) {
                    chartItems = items;
                    renderChart();
                    chartRangeCache[fetchCacheKey] = items;
                }
                resolve(true);
                runPendingChartRefresh();
            }

            var rangeQuery = '&start_time=' + encodeURIComponent(new Date(fetchFromTs).toISOString()) +
                '&end_time=' + encodeURIComponent(new Date(fetchToTs).toISOString());
            function temperatureLogsUrl(offset, scoped) {
                return URLS.temperatureLogs + '?limit=1&offset=' + offset + (scoped ? rangeQuery : '');
            }

            function probeRecordedAt(offset) {
                return apiFetchRetry(temperatureLogsUrl(offset, false)).then(function (res) {
                    if (!res.ok || !res.body.success) return null;
                    var items = (res.body.data && res.body.data.items) || [];
                    return items.length ? new Date(items[0].recorded_at).getTime() : null;
                }).catch(function () { return null; });
            }

            // Smallest offset whose reading is at/before rangeToTs — offset
            // increases as readings get older (the API is always newest-first).
            function findStartOffset(total, upperBoundTs) {
                var lo = 0, hi = total;
                function step() {
                    if (lo >= hi) return Promise.resolve(lo);
                    var mid = Math.floor((lo + hi) / 2);
                    return probeRecordedAt(mid).then(function (ts) {
                        if (ts === null || ts <= upperBoundTs) hi = mid; else lo = mid + 1;
                        return step();
                    });
                }
                return step();
            }

            function sampleRange(startOffset, endOffset, scoped) {
                var lastOffset = Math.max(startOffset, endOffset);
                var count = Math.min(CHART_MAX_POINTS, lastOffset - startOffset + 1);
                var offsets = [];
                for (var i = 0; i < count; i++) {
                    offsets.push(Math.round(startOffset + ((lastOffset - startOffset) * i / Math.max(1, count - 1))));
                }
                Promise.all(offsets.map(function (offset) {
                    return apiFetchRetry(temperatureLogsUrl(offset, scoped)).then(function (res) {
                        if (!res.ok || !res.body.success) return null;
                        return ((res.body.data && res.body.data.items) || [])[0] || null;
                    }).catch(function () { return null; });
                })).then(function (items) {
                    var readings = items.filter(Boolean);
                    finish(readings, readings.length === 0);
                }).catch(function () { finish([], true); });
            }

            apiFetchRetry(temperatureLogsUrl(0, true)).then(function (res) {
                if (!res.ok || !res.body.success) { finish([], true); return; }
                var total = (res.body.data && res.body.data.total) || 0;
                if (!total) { finish([], false); return; }
                var first = ((res.body.data && res.body.data.items) || [])[0];
                var firstTs = first ? new Date(first.recorded_at).getTime() : NaN;
                // A matching first timestamp confirms this service applied the
                // requested range. Sample that small, already-filtered set.
                if (!isNaN(firstTs) && firstTs >= fetchFromTs && firstTs <= fetchToTs) {
                    sampleRange(0, total - 1, true);
                    return;
                }
                // Ranges extending through "now" already start at offset 0 —
                // only a range whose upper bound is meaningfully in the past
                // (Yesterday, or a Custom range not ending today) needs the
                // search to skip past newer, irrelevant rows first.
                var startPromise = fetchToTs < Date.now() - 5000
                    ? findStartOffset(total, fetchToTs) : Promise.resolve(0);
                // Both bounds are independent, so locate them concurrently
                // instead of serially scanning before rendering the chart.
                Promise.all([startPromise, findStartOffset(total, fetchFromTs)]).then(function (bounds) {
                    sampleRange(bounds[0], bounds[1]);
                });
            }).catch(function () {
                finish([], true);
            });
        });
    }

    // Shared by both selectRange() (quick presets, auto-applied) and
    // applyDashboardRange() (the Apply button, for Custom Range) — assumes
    // currentRange/rangeFromTs/rangeToTs are already set by the caller.
    // Cache-first: if this range was already loaded this page-session, the
    // chart repaints from that instantly (no loading overlay, no network
    // wait) while a silent background refetch keeps the cache current —
    // otherwise it's a normal (non-silent) fetch. Returns a Promise<bool>
    // matching fetchChartData's own success/failure contract.
    function applyRangeCore() {
        updateActiveFilterIndicator();
        var cached = chartRangeCache[chartRangeCacheKey(currentRange, rangeFromTs, rangeToTs)];
        if (cached) {
            chartItems = cached;
            renderChart();
            showTempApplyConfirmation();
            fetchChartData(true); // keep the cache from going stale; deliberately not awaited — this repaint already happened
            return Promise.resolve(true);
        }
        return fetchChartData().then(function (ok) {
            if (ok) showTempApplyConfirmation();
            return ok;
        });
    }

    // Highlights the button, fills the From/To fields (so they always show
    // real dates, never blank/dd-mm-yyyy), and — for the four computed
    // presets — applies and fetches IMMEDIATELY, no Apply click needed.
    // Custom Range is the one exception: it leaves the fields alone (the
    // operator picks their own dates) and stays gated behind Apply, since
    // there's nothing valid to load until both dates are actually chosen.
    function selectRange(range) {
        pendingRangePreset = range;
        highlightRangeButton(range);
        if (range === 'custom') return;
        var bounds = computeRangeBounds(range);
        el('eidli-temp-from').value = fmtDateInputValue(bounds.from);
        el('eidli-temp-to').value = fmtDateInputValue(bounds.to);

        currentRange = range;
        customMultiDay = false;
        rangeFromTs = bounds.from; rangeToTs = bounds.to;
        applyRangeCore();
    }

    // Only reached for Custom Range now (quick presets auto-apply from
    // selectRange() above) — or as a manual re-trigger if the operator
    // hand-edits the From/To fields after a preset already populated them.
    // Reads whatever's currently in the fields (so a hand-edit on top of a
    // preset is honored), validates, and only then fetches. If the fields
    // still match what the highlighted preset computes, that preset stays
    // the applied range (keeps "Today" live-refreshing, chart label
    // formatting etc. correct); otherwise this becomes a custom range
    // regardless of which button was last clicked — keeps the chart,
    // fields, and active-filter indicator from ever disagreeing.
    function applyDashboardRange() {
        if (chartApplyInFlight) return;
        var fromVal = el('eidli-temp-from').value;
        var toVal = el('eidli-temp-to').value;
        if (!fromVal || !toVal) { window.showToast('danger', 'Select both a From and To date.'); return; }
        var fromTs = new Date(fromVal + 'T00:00:00+05:30').getTime();
        var toTs = new Date(toVal + 'T23:59:59.999+05:30').getTime();
        if (fromTs > toTs) { window.showToast('danger', 'The From date must be before the To date.'); return; }

        var presetBounds = pendingRangePreset !== 'custom' ? computeRangeBounds(pendingRangePreset) : null;
        var matchesPreset = presetBounds && fmtDateInputValue(presetBounds.from) === fromVal && fmtDateInputValue(presetBounds.to) === toVal;
        currentRange = matchesPreset ? pendingRangePreset : 'custom';
        customMultiDay = (fromVal !== toVal);
        pendingRangePreset = currentRange;
        highlightRangeButton(currentRange);
        rangeFromTs = fromTs; rangeToTs = toTs;

        chartApplyInFlight = true;
        var btn = el('eidli-temp-apply');
        var originalLabel = btn.textContent;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Applying…';

        applyRangeCore().then(function (ok) {
            chartApplyInFlight = false;
            if (ok) {
                btn.textContent = '✓ Applied';
                setTimeout(function () {
                    btn.disabled = false;
                    btn.textContent = originalLabel;
                }, 2000);
            } else {
                btn.disabled = false;
                btn.textContent = originalLabel;
                // Explicitly says what's actually on screen (the chart is
                // never cleared on a failed reload — see finish() above) so
                // this doesn't read as "nothing loaded" when something —
                // just not this range — clearly did.
                window.showToast('danger', 'Couldn\'t load data for this range — the machine service didn\'t respond in time. The chart still shows the previously loaded range; try Apply again.');
            }
        });
    }

    // --- recent heating cycles (latest 3) ---------------------------------------

    function renderCycleRow(c) {
        var peak = c.heater_off_at ? fmtTemp(c.peak_temperature) : 'Pending';
        var restart = c.heater_restart_at ? fmtTemp(c.restart_temperature) : ((c.status || '').toLowerCase() === 'abandoned' ? 'Not reached' : 'Pending');
        var trail = c.duration_seconds != null ? fmtDuration(c.duration_seconds) : ((c.status || '').toLowerCase() === 'abandoned' ? 'Abandoned' : '');
        return '<div class="eidli-row-compact">' +
            '<div>' +
            '<div><strong>Cycle #' + esc(c.cycle_number) + '</strong> ' + E.cycleStatusBadge(c.status) + '</div>' +
            '<div class="text-muted small">' + esc(fmtTemp(c.start_temperature)) + ' → ' + esc(peak) + ' → ' + esc(restart) + '</div>' +
            '</div>' +
            '<div class="eidli-row-time">' + esc(trail) + '</div>' +
            '</div>';
    }

    function refreshCycles() {
        if (!CONFIGURED) return;
        apiFetch(URLS.heatingCycles + '?limit=25').then(function (res) {
            if (!res.ok || !res.body.success) { el('eidli-recent-cycles-body').innerHTML = '<div class="eidli-section-error">Unable to load heating cycles.</div>'; return; }
            var items = (res.body.data && res.body.data.items) || [];
            lastCycles = items;
            items = items.slice().sort(function (a, b) { return new Date(b.heater_on_at) - new Date(a.heater_on_at); }).slice(0, 3);
            el('eidli-recent-cycles-body').innerHTML = items.length
                ? items.map(renderCycleRow).join('')
                : '<div class="eidli-section-empty">No heating cycles yet.</div>';
        }).catch(function () { el('eidli-recent-cycles-body').innerHTML = '<div class="eidli-section-error">Unable to load heating cycles.</div>'; });
    }

    // --- recent events (latest 5) ------------------------------------------------

    function renderEventRow(e) {
        return '<div class="eidli-row-compact">' +
            '<div>' +
            '<div><strong>' + esc(E.titleCase(e.event_type)) + '</strong></div>' +
            '<div class="text-muted small">' + esc(e.event_message || '—') + '</div>' +
            '</div>' +
            '<div class="eidli-row-time">' + esc(fmtTime(e.created_at)) + '</div>' +
            '</div>';
    }

    function refreshRecentEvents() {
        if (!CONFIGURED) return;
        apiFetch(URLS.events + '?limit=5&offset=0').then(function (res) {
            if (!res.ok || !res.body.success) { el('eidli-recent-events-body').innerHTML = '<div class="eidli-section-error">Unable to load events.</div>'; return; }
            var items = (res.body.data && res.body.data.items) || [];
            items = items.slice().sort(function (a, b) { return new Date(b.created_at) - new Date(a.created_at); });
            el('eidli-recent-events-body').innerHTML = items.length
                ? items.map(renderEventRow).join('')
                : '<div class="eidli-section-empty">No events yet.</div>';
        }).catch(function () { el('eidli-recent-events-body').innerHTML = '<div class="eidli-section-error">Unable to load events.</div>'; });
    }

    // --- session summary strip ---------------------------------------------------
    //
    // Backed by GET /sessions/today (DailySessionSummaryResponse) — a proper
    // operator-local-day count from the backend, not derived client-side
    // from whatever page of /sessions happens to be loaded. Fetched once on
    // load (matches every other "on load, not polled" section here); if it
    // fails, retried on the same 20s cadence the rest of this page's
    // retryable fetches use.

    var dailySummary = null;
    var dailySummaryFailed = false;
    var dailySummaryRetryTimer = null;

    function refreshDailySummary() {
        if (!CONFIGURED) return Promise.resolve();
        return apiFetch(URLS.sessionsToday).then(function (res) {
            if (res.ok && res.body.success) {
                dailySummary = res.body.data;
                dailySummaryFailed = false;
                if (dailySummaryRetryTimer) { clearInterval(dailySummaryRetryTimer); dailySummaryRetryTimer = null; }
            } else {
                dailySummaryFailed = true;
                if (!dailySummaryRetryTimer) dailySummaryRetryTimer = setInterval(function () { refreshDailySummary().then(renderTodayStrip); }, 20000);
            }
        }).catch(function () {
            dailySummaryFailed = true;
            if (!dailySummaryRetryTimer) dailySummaryRetryTimer = setInterval(function () { refreshDailySummary().then(renderTodayStrip); }, 20000);
        });
    }

    function renderTodayStrip() {
        var strip = el('eidli-today-strip');
        var status = E.getLastStatus();
        var items = [];
        items.push({ label: 'Sessions Completed Today', value: dailySummary ? dailySummary.sessions_completed_today : (dailySummaryFailed ? '—' : '…') });
        items.push({ label: 'Current Session', value: currentSession ? '#' + esc(currentSession.session_number) : 'None active' });
        items.push({ label: 'Current Session Cycles', value: currentSession && currentSession.heating_cycle_count != null ? currentSession.heating_cycle_count : '—' });
        items.push({ label: 'Lifetime Sessions', value: dailySummary ? dailySummary.lifetime_sessions : (dailySummaryFailed ? '—' : '…') });
        var html = '';
        items.forEach(function (it) {
            html += '<div class="eidli-today-item"><div class="eidli-stat-label">' + esc(it.label) + '</div><div class="eidli-stat-value">' + esc(it.value) + '</div></div>';
        });
        if (status) {
            var power = null;
            ['power', 'power_watts'].some(function (k) { if (status[k] != null) { power = status[k]; return true; } return false; });
            if (power != null) {
                html += '<div class="eidli-today-item"><div class="eidli-stat-label">Power</div><div class="eidli-stat-value">' + esc(power) + ' W</div></div>';
            }
        }
        strip.innerHTML = html;
    }

    // --- remote commands (heater on/off, restart) --------------------------------

    function setCommandStatus(text, cls) {
        var e = el('eidli-command-status');
        e.textContent = text;
        e.className = 'eidli-cmd-status ' + (cls || '');
    }

    // The heater toggle intentionally does NOT go through dispatchCommand's
    // ack-poll flow (that's kept as-is for Restart, which still shows
    // "Sending… / Published — waiting for ack… / confirmed"). A toggle
    // switch's whole UX point is immediate visual feedback: the checkbox
    // has already flipped natively by the time this fires (it's a change
    // handler), so this just confirms the POST landed, toasts, and — only
    // on failure — snaps the switch back to the machine's last confirmed
    // heater_status rather than leaving it on the wrong optimistic position.
    // The next status poll (3s) will correct it to ground truth regardless.
    function finishHeaterToggle(turnOn, ok) {
        heaterToggleInFlight = false;
        if (ok) {
            heaterDesiredState = turnOn;
            heaterCommandHoldUntil = Date.now() + HEATER_STATUS_GRACE_MS;
        } else {
            heaterDesiredState = null;
            heaterCommandHoldUntil = 0;
        }
        updateControlsDisabled(E.getLastStatus());
        updateHeaterToggleState(E.getLastStatus());
    }

    function pollHeaterAck(requestId, label, turnOn) {
        if (!requestId) {
            setCommandStatus('Heater ' + label + ' command accepted.', 'state-success');
            finishHeaterToggle(turnOn, true);
            return;
        }
        var attempts = 0, maxAttempts = 8;
        var iv = setInterval(function () {
            attempts++;
            apiFetch(URLS.commands + '?limit=20').then(function (res) {
                if (res.ok && res.body.success) {
                    var items = (res.body.data && res.body.data.items) || [];
                    var match = null;
                    for (var i = 0; i < items.length; i++) { if (items[i].request_id === requestId) { match = items[i]; break; } }
                    if (match && match.status !== 'pending') {
                        clearInterval(iv);
                        if (match.status === 'success') {
                            setCommandStatus('Heater ' + label + ' acknowledged by the machine.', 'state-success');
                            window.showToast('success', 'Heater turned ' + label + '.');
                            finishHeaterToggle(turnOn, true);
                        } else {
                            setCommandStatus((match.response_message || 'Heater ' + label + ' failed.'), 'state-failed');
                            window.showToast('danger', 'Heater ' + label + ' failed.');
                            finishHeaterToggle(turnOn, false);
                        }
                        return;
                    }
                }
                if (attempts >= maxAttempts) {
                    clearInterval(iv);
                    setCommandStatus('Heater ' + label + ' still pending - check History > Commands.', 'state-pending');
                    finishHeaterToggle(turnOn, true);
                }
            }).catch(function () {
                if (attempts >= maxAttempts) {
                    clearInterval(iv);
                    setCommandStatus('Heater ' + label + ' sent - could not confirm the outcome yet.', 'state-pending');
                    finishHeaterToggle(turnOn, true);
                }
            });
        }, 2000);
    }

    function toggleHeater(turnOn) {
        if (heaterToggleInFlight) return;
        var toggle = el('eidli-heater-toggle');
        var currentMode = ((lastSettings && lastSettings.mode) || '').toLowerCase();
        if (currentMode !== 'manual') {
            updateHeaterToggleState(E.getLastStatus());
            window.showToast('warning', 'Switch to Manual mode before using heater control.');
            return;
        }
        heaterToggleInFlight = true;
        if (toggle) toggle.disabled = true;
        var label = turnOn ? 'ON' : 'OFF';
        setCommandStatus('Sending heater ' + label + '...', 'state-pending');
        apiFetch(turnOn ? URLS.heaterOn : URLS.heaterOff, { method: 'POST' }).then(function (res) {
            if (res.ok && res.body.success) {
                var payload = res.body.data || {};
                heaterDesiredState = turnOn;
                heaterCommandHoldUntil = Date.now() + HEATER_STATUS_GRACE_MS;
                if (toggle) toggle.checked = turnOn;
                el('eidli-grid-heater').innerHTML = E.heaterBadge(turnOn ? 'on' : 'off');
                setCommandStatus('Heater ' + label + ' published - waiting for the machine to acknowledge...', 'state-pending');
                pollHeaterAck(payload.request_id, label, turnOn);
            } else {
                window.showToast('danger', 'Failed to turn heater ' + label + ': ' + errMsg(res, 'unknown error'));
                finishHeaterToggle(turnOn, false);
            }
        }).catch(function () {
            window.showToast('danger', 'Failed to turn heater ' + label + ': network error.');
            finishHeaterToggle(turnOn, false);
        });
    }

    function dispatchCommand(url, label) {
        if (commandInFlight) return;
        commandInFlight = true;
        updateControlsDisabled(E.getLastStatus());
        setCommandStatus('Sending ' + label + '…', 'state-pending');
        apiFetch(url, { method: 'POST' }).then(function (res) {
            if (!res.ok || !res.body.success) {
                commandInFlight = false; updateControlsDisabled(E.getLastStatus());
                var msg = errMsg(res, 'Command failed.');
                setCommandStatus('Failed — ' + msg, 'state-failed');
                window.showToast('danger', label + ' failed: ' + msg);
                return;
            }
            var payload = res.body.data || {};
            setCommandStatus('Published — waiting for the machine to acknowledge…', 'state-pending');
            pollCommandAck(payload.request_id, label);
        }).catch(function () {
            commandInFlight = false; updateControlsDisabled(E.getLastStatus());
            setCommandStatus('Failed — could not reach the server.', 'state-failed');
            window.showToast('danger', label + ' failed: network error.');
        });
    }

    function pollCommandAck(requestId, label) {
        if (!requestId) {
            commandInFlight = false; updateControlsDisabled(E.getLastStatus());
            setCommandStatus('Sent — command accepted.', 'state-success');
            return;
        }
        var attempts = 0, maxAttempts = 8;
        var iv = setInterval(function () {
            attempts++;
            apiFetch(URLS.commands + '?limit=20').then(function (res) {
                if (res.ok && res.body.success) {
                    var items = (res.body.data && res.body.data.items) || [];
                    var match = null;
                    for (var i = 0; i < items.length; i++) { if (items[i].request_id === requestId) { match = items[i]; break; } }
                    if (match && match.status !== 'pending') {
                        clearInterval(iv);
                        commandInFlight = false; updateControlsDisabled(E.getLastStatus());
                        if (match.status === 'success') {
                            setCommandStatus(label + ' acknowledged by the machine ✓', 'state-success');
                            window.showToast('success', label + ' confirmed by the machine.');
                        } else if (match.status === 'timeout') {
                            setCommandStatus(label + ' timed out ⚠', 'state-failed');
                            window.showToast('danger', label + ' timed out.');
                        } else {
                            setCommandStatus((match.response_message || label + ' failed.'), 'state-failed');
                            window.showToast('danger', label + ' failed.');
                        }
                        return;
                    }
                }
                if (attempts >= maxAttempts) {
                    clearInterval(iv);
                    commandInFlight = false; updateControlsDisabled(E.getLastStatus());
                    setCommandStatus('Still pending — check History → Commands.', 'state-pending');
                }
            }).catch(function () {
                if (attempts >= maxAttempts) {
                    clearInterval(iv);
                    commandInFlight = false; updateControlsDisabled(E.getLastStatus());
                    setCommandStatus('Sent — could not confirm the outcome yet.', 'state-pending');
                }
            });
        }, 2000);
    }

    // --- wiring -----------------------------------------------------------------

    function bindControls() {
        el('eidli-heater-toggle').addEventListener('change', function (e) {
            toggleHeater(e.target.checked);
        });
        el('eidli-restart-btn').addEventListener('click', function () {
            if (!confirm('Restart the machine remotely?\n\nIt will briefly go offline.')) return;
            dispatchCommand(URLS.restart, 'Restart');
        });
        // Refreshes the CURRENTLY APPLIED range only — rangeFromTs/rangeToTs,
        // the visible From/To fields, and the highlighted quick-range button
        // are all left exactly as they are. blur() once the fetch settles
        // removes the focus ring Bootstrap leaves on the button after a
        // click, rather than leaving it visibly "stuck" highlighted.
        el('eidli-temp-refresh').addEventListener('click', function () {
            var btn = this;
            fetchChartData().then(function () { btn.blur(); });
        });
        document.querySelectorAll('#eidli-temp-range-group button').forEach(function (b) {
            b.addEventListener('click', function () { selectRange(b.getAttribute('data-range')); });
        });
        el('eidli-temp-apply').addEventListener('click', applyDashboardRange);
        document.querySelectorAll('#eidli-mode-toggle button').forEach(function (b) {
            b.addEventListener('click', function () { switchMode(b.getAttribute('data-mode')); });
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
            var sess = sessionStorage.getItem('eidli_cache_session');
            if (sess !== null) { currentSession = JSON.parse(sess); renderSessionMini(currentSession); }
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
            el('eidli-session-mini').innerHTML = '<div class="eidli-section-empty">Not connected.</div>';
            el('eidli-recent-cycles-body').innerHTML = '<div class="eidli-section-empty">Not connected.</div>';
            el('eidli-recent-events-body').innerHTML = '<div class="eidli-section-empty">Not connected.</div>';
            el('eidli-today-strip').innerHTML = '<div class="eidli-section-empty">Not connected.</div>';
            return;
        }

        hydrateFromCache();

        E.onStatus(function () {
            if (firstLiveStatusLogged) return;
            firstLiveStatusLogged = true;
            console.debug('[dashboard-timing] first live temperature/heater/machine/sensor status displayed at', performance.now().toFixed(0), 'ms since navigation start');
        });
        E.onStatus(renderStatusGrid);
        // Current Session (+ elapsed, + cycle count, both embedded in the
        // session object) now rides the same 3s shared /status poll instead
        // of its own 20s timer, so it counts as "live" alongside
        // temperature/heater/machine/sensor rather than lagging behind them.
        E.onStatus(refreshSession);
        refreshSettings();
        refreshSession();
        refreshCycles();
        // Initial chart load bypasses the Apply-button flow — Today's data
        // should be visible immediately on open, not gated behind an
        // explicit click. Sets up the same state applyDashboardRange()
        // would (fields, currentRange, active-filter indicator) so
        // everything's already synchronized before the operator ever
        // touches these controls.
        (function () {
            pendingRangePreset = 'today';
            currentRange = 'today';
            highlightRangeButton('today');
            var bounds = computeRangeBounds('today');
            el('eidli-temp-from').value = fmtDateInputValue(bounds.from);
            el('eidli-temp-to').value = fmtDateInputValue(bounds.to);
            rangeFromTs = bounds.from; rangeToTs = bounds.to;
            applyRangeCore(); // same cache-first path as selectRange() — nothing cached yet on a real page load, so this just falls through to a normal fetch
        })();
        refreshRecentEvents();
        refreshDailySummary().then(renderTodayStrip);

        setInterval(function () {
            if (document.visibilityState !== 'visible') return;
            refreshCycles(); refreshRecentEvents();
            // Live updates only apply to the Today filter — historical
            // ranges show stored data only, no background refetching.
            // silent=true: this is a background refresh of an
            // already-rendered chart, not a user-initiated one — no
            // "Loading…" flash, no visible disruption if nothing changed.
            if (currentRange === 'today' && !chartFetchInFlight) {
                var bounds = computeRangeBounds('today');
                rangeFromTs = bounds.from; rangeToTs = bounds.to;
                fetchChartData(true);
            }
        }, 20000);
    });
})();
