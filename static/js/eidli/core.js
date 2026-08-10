/*
 * Electric Idli Machine — shared core (loaded on Dashboard, History and
 * Settings pages before the page-specific script).
 *
 * Owns:
 *   - the Flask-proxy API client (apiFetch) — talks only to this POS's own
 *     /machines/idli/api/* routes, never the FastAPI backend directly.
 *   - formatting helpers, all timestamps forced to Asia/Kolkata regardless
 *     of the viewing device's own timezone (operators may check the
 *     dashboard from anywhere; the machine itself is fixed in India).
 *   - the ONE shared 3s poll of /status, which also drives the header's
 *     connection badge + "last seen" + machine name on every page. Pages
 *     that need the full status payload (temperature, heater, sensor...)
 *     subscribe via Eidli.onStatus() instead of starting their own interval.
 */
(function (window) {
    var CONFIG = window.EIDLI_CONFIG || {};
    var CONFIGURED = !!CONFIG.configured;
    var URLS = CONFIG.urls || {};

    function el(id) { return document.getElementById(id); }

    function esc(s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // "heating_cycle_completed" -> "Heating Cycle Completed" — a generic
    // transform rather than a hardcoded lookup table, so it covers every
    // backend event/command name (documented or future) without drifting
    // out of sync with the backend's enum list.
    function titleCase(s) {
        if (!s) return '';
        return String(s).split('_').map(function (w) {
            return w.charAt(0).toUpperCase() + w.slice(1);
        }).join(' ');
    }

    // --- formatting — always Asia/Kolkata, independent of viewer's device tz ---

    var IST_TZ = 'Asia/Kolkata';

    function fmtTemp(v) {
        if (v === null || v === undefined || v === '') return '—';
        var n = Number(v);
        if (isNaN(n)) return '—';
        return n.toFixed(1) + '°C';
    }

    function fmtDateTime(iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-IN', { timeZone: IST_TZ, day: '2-digit', month: 'short', year: 'numeric' }) +
            ' · ' + d.toLocaleTimeString('en-IN', { timeZone: IST_TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
    }

    function fmtDate(iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('en-IN', { timeZone: IST_TZ, day: '2-digit', month: 'short', year: 'numeric' });
    }

    function fmtTime(iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleTimeString('en-IN', { timeZone: IST_TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
    }

    function nowText() {
        return fmtDateTime(new Date().toISOString());
    }

    // 'YYYY-MM-DD' for `d`'s calendar date in Asia/Kolkata — same IST_TZ used
    // by every fmt* function above, just formatted for machine consumption
    // (e.g. an <input type="date"> value) instead of display. en-CA is the
    // one common locale whose date format is already ISO YYYY-MM-DD.
    function istDateISO(d) {
        return d.toLocaleDateString('en-CA', { timeZone: IST_TZ });
    }

    function fmtRelative(iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        var diffSec = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
        if (diffSec < 5) return 'just now';
        if (diffSec < 60) return diffSec + 's ago';
        if (diffSec < 3600) return Math.floor(diffSec / 60) + 'm ago';
        if (diffSec < 86400) return Math.floor(diffSec / 3600) + 'h ago';
        return fmtDateTime(iso);
    }

    function fmtDuration(seconds) {
        if (seconds === null || seconds === undefined) return '—';
        var total = Math.floor(Number(seconds));
        if (isNaN(total) || total < 0) return '—';
        var h = Math.floor(total / 3600);
        var m = Math.floor((total % 3600) / 60);
        var s = total % 60;
        if (h > 0) return h + 'h ' + m + 'm ' + s + 's';
        if (m > 0) return m + 'm ' + s + 's';
        return s + 's';
    }

    // --- badges ----------------------------------------------------------------

    function badge(text, cls) { return '<span class="eidli-badge ' + cls + '">' + esc(text) + '</span>'; }

    // HEATER ON and HEATING both use eidli-b-good — the same green as
    // Sensor Connected — per explicit request for one consistent "good/
    // active" status color across the dashboard instead of amber/warn.
    function heaterBadge(status) {
        var s = (status || '').toLowerCase();
        if (s === 'on') return badge('🟢 HEATER ON', 'eidli-b-good');
        if (s === 'off') return badge('⚪ HEATER OFF', 'eidli-b-neutral');
        return badge('UNKNOWN', 'eidli-b-neutral');
    }

    function sensorBadge(status) {
        var s = (status || '').toLowerCase();
        if (s === 'connected') return badge('CONNECTED', 'eidli-b-good');
        if (s === 'disconnected') return badge('DISCONNECTED', 'eidli-b-bad');
        if (s === 'error') return badge('FAULT', 'eidli-b-bad');
        return badge('UNKNOWN', 'eidli-b-neutral');
    }

    function machineStateBadge(state) {
        var s = (state || '').toLowerCase();
        if (s === 'fault' || s === 'offline') return badge(s.toUpperCase(), 'eidli-b-bad');
        if (s === 'running' || s === 'heating' || s === 'cooking') return badge((s === 'heating' ? '🟢 ' : '') + s.toUpperCase(), 'eidli-b-good');
        if (s === 'completed') return badge(s.toUpperCase(), 'eidli-b-good');
        if (s === 'idle') return badge(s.toUpperCase(), 'eidli-b-neutral');
        if (!s) return badge('UNKNOWN', 'eidli-b-neutral');
        return badge(s.toUpperCase(), 'eidli-b-neutral');
    }

    function sessionStatusBadge(status) {
        var s = (status || '').toLowerCase();
        if (s === 'active') return badge('ACTIVE', 'eidli-b-warn');
        if (s === 'completed') return badge('COMPLETED', 'eidli-b-good');
        if (s === 'stopped') return badge('STOPPED', 'eidli-b-neutral');
        if (s === 'interrupted') return badge('INTERRUPTED', 'eidli-b-bad');
        if (s === 'faulted') return badge('FAULTED', 'eidli-b-bad');
        return badge((s || 'UNKNOWN').toUpperCase(), 'eidli-b-neutral');
    }

    function cycleStatusBadge(status) {
        var s = (status || '').toLowerCase();
        if (s === 'in_progress') return badge('IN PROGRESS', 'eidli-b-warn');
        if (s === 'completed') return badge('COMPLETED', 'eidli-b-good');
        if (s === 'abandoned') return badge('ABANDONED', 'eidli-b-bad');
        return badge((s || 'UNKNOWN').toUpperCase(), 'eidli-b-neutral');
    }

    function commandStatusBadge(status) {
        var s = (status || '').toLowerCase();
        if (s === 'pending') return badge('PENDING', 'eidli-b-warn');
        if (s === 'success') return badge('SUCCESS', 'eidli-b-good');
        if (s === 'failed') return badge('FAILED', 'eidli-b-bad');
        if (s === 'timeout') return badge('TIMEOUT', 'eidli-b-bad');
        return badge((s || 'UNKNOWN').toUpperCase(), 'eidli-b-neutral');
    }

    function modeBadge(mode) {
        var s = (mode || '').toLowerCase();
        if (s === 'auto') return badge('AUTOMATIC', 'eidli-b-good');
        if (s === 'manual') return badge('MANUAL', 'eidli-b-warn');
        return badge('UNKNOWN', 'eidli-b-neutral');
    }

    // --- fetch helper ------------------------------------------------------------

    function apiFetch(url, options) {
        options = options || {};
        options.credentials = 'same-origin';
        // 'no-store' so a hard refresh is never needed to see fresh machine
        // telemetry — every call through here (status, session, chart,
        // events...) always hits the network, never the browser's HTTP
        // cache, regardless of what Cache-Control the response carries.
        if (!options.cache) options.cache = 'no-store';
        if (options.method && options.method !== 'GET') {
            options.headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
        }
        return fetch(url, options).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (body) {
                return { ok: r.ok, status: r.status, body: body };
            });
        });
    }

    function errMsg(res, fallback) {
        return (res && res.body && res.body.message) || fallback;
    }

    // --- shared header: connection badge, last-seen, machine name, clock --------
    //
    // Every page (Dashboard/History/Settings) calls Eidli.startHeader() once.
    // It owns the single 3s /status poll; anything that needs the full
    // payload (Dashboard's live status grid) subscribes via Eidli.onStatus()
    // rather than opening a second interval against the same endpoint.

    var statusListeners = [];
    var lastStatus = null;

    function onStatus(fn) { statusListeners.push(fn); }
    function getLastStatus() { return lastStatus; }

    function setConnBadge(isOnline) {
        var b = el('eidli-conn-badge');
        if (!b) return;
        if (isOnline === true) { b.className = 'eidli-conn-badge eidli-conn-online'; b.innerHTML = '<i class="ri-checkbox-blank-circle-fill"></i> ONLINE'; }
        else if (isOnline === false) { b.className = 'eidli-conn-badge eidli-conn-offline'; b.innerHTML = '<i class="ri-checkbox-blank-circle-fill"></i> OFFLINE'; }
        else { b.className = 'eidli-conn-badge eidli-conn-connecting'; b.innerHTML = '<i class="ri-checkbox-blank-circle-fill"></i> CONNECTING…'; }
    }

    var statusFetchSeq = 0;
    var firstRequestLogged = false; // temporary timing instrumentation, see the dashboard-load investigation

    function pollStatusOnce() {
        if (!CONFIGURED) { setConnBadge(false); return; }
        if (!firstRequestLogged) {
            firstRequestLogged = true;
            console.debug('[dashboard-timing] first API request (/status) dispatched at', performance.now().toFixed(0), 'ms since navigation start');
        }
        // A slow response can still be in flight when the next 3s tick
        // fires another — this sequence number makes sure an older
        // response landing after a newer one is just ignored, so a stale
        // poll can never overwrite what a fresher one already rendered.
        var seq = ++statusFetchSeq;
        apiFetch(URLS.status).then(function (res) {
            if (seq !== statusFetchSeq) return;
            if (!res.ok || !res.body.success) {
                setConnBadge(null);
                return;
            }
            lastStatus = res.body.data || {};
            setConnBadge(!!lastStatus.is_online);
            var seenEl = el('eidli-last-seen');
            if (seenEl) seenEl.textContent = 'Last telemetry: ' + fmtRelative(lastStatus.last_seen);
            statusListeners.forEach(function (fn) { try { fn(lastStatus); } catch (e) {} });
        }).catch(function () {
            if (seq !== statusFetchSeq) return;
            setConnBadge(null);
        });
    }

    var machineNameRetryTimer = null;

    function fetchMachineName() {
        if (!CONFIGURED) return;
        var nameEl = el('eidli-machine-name');
        apiFetch(URLS.machine).then(function (res) {
            if (res.ok && res.body.success && res.body.data) {
                if (nameEl) nameEl.textContent = res.body.data.machine_name || 'Electric Idli Machine';
                if (machineNameRetryTimer) { clearInterval(machineNameRetryTimer); machineNameRetryTimer = null; }
            } else {
                if (nameEl && !nameEl.textContent.trim()) nameEl.textContent = 'Electric Idli Machine';
                if (!machineNameRetryTimer) machineNameRetryTimer = setInterval(fetchMachineName, 20000);
            }
        }).catch(function () {
            if (nameEl && !nameEl.textContent.trim()) nameEl.textContent = 'Electric Idli Machine';
            if (!machineNameRetryTimer) machineNameRetryTimer = setInterval(fetchMachineName, 20000);
        });
    }

    function startClock() {
        var clockEl = el('eidli-clock');
        if (!clockEl) return;
        function tick() { clockEl.textContent = nowText(); }
        tick();
        setInterval(tick, 1000);
    }

    function startHeader() {
        if (!CONFIGURED) { setConnBadge(false); startClock(); return; }
        fetchMachineName();
        pollStatusOnce();
        startClock();
        setInterval(function () {
            if (document.visibilityState === 'visible') pollStatusOnce();
        }, 3000);
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible') pollStatusOnce();
        });
    }

    window.Eidli = {
        CONFIG: CONFIG, CONFIGURED: CONFIGURED, URLS: URLS,
        el: el, esc: esc, titleCase: titleCase,
        fmtTemp: fmtTemp, fmtDateTime: fmtDateTime, fmtDate: fmtDate, fmtTime: fmtTime,
        fmtRelative: fmtRelative, fmtDuration: fmtDuration, istDateISO: istDateISO,
        badge: badge, heaterBadge: heaterBadge, sensorBadge: sensorBadge,
        machineStateBadge: machineStateBadge, sessionStatusBadge: sessionStatusBadge,
        cycleStatusBadge: cycleStatusBadge, commandStatusBadge: commandStatusBadge, modeBadge: modeBadge,
        apiFetch: apiFetch, errMsg: errMsg,
        startHeader: startHeader, onStatus: onStatus, getLastStatus: getLastStatus
    };
})(window);
