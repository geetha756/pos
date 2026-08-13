/*
 * Electric Idli Machine — History page (Events / Commands). An
 * investigation/audit workspace, not the live-ops view.
 *
 * Date-range filtering is server-side: createList's load() sends
 * start_time/end_time (full IST ISO-8601, e.g. 2026-08-04T00:00:00+05:30)
 * on every fetch once a range is Applied, per the backend contract added in
 * commit 3bb73e1. The dateFromTs/dateToTs epoch-ms pair below still drives
 * a client-side re-filter on top of that as a harmless redundant pass over
 * whatever the server already returned — kept rather than removed since the
 * server is the source of truth for the actual result set either way.
 *
 * Apply/Clear re-fetch the *currently active* tab from the backend (via
 * apiFetch, same as the per-section Refresh buttons) before re-applying the
 * filter, so the filtered view reflects fresh data instead of whatever
 * happened to already be cached — and mark the other three tabs stale so
 * they re-fetch (picking up the new range) the next time the user actually
 * switches to them, instead of eagerly fetching all four on every click.
 */
(function () {
    var E = window.Eidli;
    var el = E.el, esc = E.esc, apiFetch = E.apiFetch, errMsg = E.errMsg;
    var fmtDateTime = E.fmtDateTime;
    var URLS = E.URLS, CONFIGURED = E.CONFIGURED;

    var HISTORY_AUTO_REFRESH_MS = 10000;
    var dateFromTs = null, dateToTs = null;
    // Server-side range for the backend's start_time/end_time contract
    // (commit 3bb73e1) — full timezone-aware ISO-8601 strings, built
    // directly from the picked date/time strings with an explicit +05:30
    // IST offset rather than parsed through Date() (which would be
    // ambiguous/local-timezone-dependent, unlike dateFromTs/dateToTs above
    // which only ever feed the client-side filter, not an outgoing
    // request). null when a boundary isn't set, so Clear sends no range
    // params at all instead of an empty string.
    var rangeStartISO = null, rangeEndISO = null;
    var currentTab = 'events';
    var applyInFlight = false;

    // --- generic paginated/filterable list -----------------------------------

    function createList(opts) {
        var items = [], offset = 0, loaded = false, loadInFlight = false, pendingReload = false;
        var lastRenderedHtml = null;
        var cacheKey = opts.cacheKey ? ('eidli_hist_cache_' + opts.cacheKey) : null;
        var PAGE = opts.page || 25;

        function applyFilters(list) {
            var out = list;
            if (opts.statusSelectId) {
                var sel = el(opts.statusSelectId);
                var sVal = sel ? sel.value : '';
                if (sVal) out = out.filter(function (i) { return (i[opts.statusField || 'status'] || '').toLowerCase() === sVal; });
            }
            if (dateFromTs) out = out.filter(function (i) { var t = i[opts.dateField]; return t && new Date(t).getTime() >= dateFromTs; });
            if (dateToTs) out = out.filter(function (i) { var t = i[opts.dateField]; return t && new Date(t).getTime() <= dateToTs; });
            return out;
        }

        function render() {
            var body = el(opts.bodyId);
            var filtered = applyFilters(items).slice().sort(function (a, b) { return new Date(b[opts.dateField]) - new Date(a[opts.dateField]); });
            var html = filtered.length
                ? opts.renderRows(filtered)
                : '<div class="eidli-section-empty">' + (items.length ? 'No records match the current filters.' : opts.emptyText) + '</div>';
            // Compares the actual rendered OUTPUT, not just item ids/count —
            // an id-only fingerprint would hide real changes on already-known
            // rows (a status flipping pending->success, an active session's
            // duration climbing), which would break live-update correctness.
            // This only skips the DOM write + afterRender listener
            // re-attachment when literally nothing about what's on screen
            // would change — the 10s auto-refresh calls render() every tick
            // regardless of whether the underlying data actually moved.
            var t0 = performance.now();
            if (html === lastRenderedHtml) {
                console.debug('[history-timing]', opts.bodyId, 'render skipped (unchanged), checked in', (performance.now() - t0).toFixed(2), 'ms');
                return;
            }
            lastRenderedHtml = html;
            body.innerHTML = html;
            if (filtered.length && opts.afterRender) opts.afterRender(body, filtered);
            console.debug('[history-timing]', opts.bodyId, 'render took', (performance.now() - t0).toFixed(1), 'ms');
        }

        // Paints whatever was cached from the last successful load, straight
        // from sessionStorage — before any fetch has even started. Doesn't
        // set loaded=true, so the real load() below still runs and silently
        // replaces this with fresh data; purely a "show something instantly"
        // step, same pattern as dashboard.js's hydrateFromCache().
        function hydrate() {
            if (!cacheKey || loaded) return;
            try {
                var cached = sessionStorage.getItem(cacheKey);
                if (cached) { items = JSON.parse(cached); render(); }
            } catch (e) {}
        }

        function load(reset) {
            if (reset) { items = []; offset = 0; }
            // Guards against firing the same fetch twice — e.g. the initial
            // eager-load-all-tabs pass and activateTab()'s own
            // not-loaded-yet check can both fire in the same synchronous
            // tick, before either's response has come back to set loaded.
            // Doesn't just drop the call, though: if it's dropped because,
            // say, Apply raced an in-flight auto-refresh tick, silently
            // discarding it would mean the new filter never actually takes
            // effect. pendingReload records that a reset was wanted and
            // reruns load(true) once the in-flight one settles, so the
            // latest requested state always eventually wins.
            if (loadInFlight) {
                if (reset) pendingReload = true;
                return Promise.resolve(true);
            }
            loadInFlight = true;
            var t0 = performance.now();
            var url = opts.url + '?limit=' + PAGE + '&offset=' + offset;
            if (rangeStartISO) url += '&start_time=' + encodeURIComponent(rangeStartISO);
            if (rangeEndISO) url += '&end_time=' + encodeURIComponent(rangeEndISO);
            return apiFetch(url).then(function (res) {
                loadInFlight = false;
                var apiMs = performance.now() - t0;
                if (!res.ok || !res.body.success) {
                    el(opts.bodyId).innerHTML = '<div class="eidli-section-error">' + opts.errorText + '</div>';
                    if (pendingReload) { pendingReload = false; load(true); }
                    return false;
                }
                var data = res.body.data || {};
                var newItems = data.items || [];
                offset += newItems.length;
                loaded = true;
                // De-dupe by id — offset-based pagination against a table that
                // keeps growing can shift rows between "Load more" clicks, so
                // the same row can reappear on the next page. Anything without
                // an id is kept as-is rather than guessed at.
                var seenIds = {};
                items.forEach(function (i) { if (i && i.id != null) seenIds[i.id] = true; });
                var freshItems = newItems.filter(function (i) { return !(i && i.id != null && seenIds[i.id]); });
                items = items.concat(freshItems);
                if (cacheKey) { try { sessionStorage.setItem(cacheKey, JSON.stringify(items)); } catch (e) {} }
                render();
                var moreBtn = el(opts.moreId);
                if (moreBtn) moreBtn.style.display = (offset < (data.total || 0)) ? 'inline-block' : 'none';
                console.debug('[history-timing]', opts.bodyId, 'API request took', apiMs.toFixed(0), 'ms');
                if (pendingReload) { pendingReload = false; load(true); }
                return true;
            }).catch(function () {
                loadInFlight = false;
                el(opts.bodyId).innerHTML = '<div class="eidli-section-error">' + opts.errorText + '</div>';
                if (pendingReload) { pendingReload = false; load(true); }
                return false;
            });
        }

        return {
            load: load, render: render, hydrate: hydrate,
            isLoaded: function () { return loaded; }, getItems: function () { return items; },
            // Forces the next activateTab() visit to re-fetch instead of
            // reusing a stale cached page — used when Apply/Clear change the
            // filter for a tab that isn't the one currently on screen.
            invalidate: function () { loaded = false; }
        };
    }

    // --- events ------------------------------------------------------------------


    function valueFromEvent(e, names) {
        var sources = [e, e && e.metadata, e && e.details, e && e.payload, e && e.data];
        for (var s = 0; s < sources.length; s++) {
            var src = sources[s];
            if (!src || typeof src !== 'object') continue;
            for (var i = 0; i < names.length; i++) {
                var val = src[names[i]];
                if (val !== undefined && val !== null && val !== '') return val;
            }
        }
        return null;
    }

    function normalizeReason(value) {
        var reason = String(value || '').toLowerCase();
        if (reason.indexOf('auto') !== -1 || reason === 'threshold' || reason === 'system') return 'automatic';
        if (reason.indexOf('manual') !== -1 || reason.indexOf('operator') !== -1 || reason === 'local') return 'manual';
        if (reason.indexOf('remote') !== -1 || reason.indexOf('command') !== -1 || reason.indexOf('mqtt') !== -1 || reason.indexOf('api') !== -1) return 'remote';
        return reason || null;
    }

    function operatingMode(e) {
        var value = valueFromEvent(e, ['operating_mode', 'control_mode', 'mode']);
        if (value === null) return null;
        var mode = String(value).toLowerCase();
        if (mode === 'auto' || mode === 'automatic') return 'Automatic';
        if (mode === 'manual') return 'Manual';
        return String(value);
    }

    function fmtEventTemp(value) {
        if (value === null || value === undefined || value === '') return null;
        var n = Number(value);
        if (isNaN(n)) return String(value);
        return (Math.round(n * 100) / 100).toString().replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1') + '�C';
    }

    function thresholdForHeaterEvent(e, turningOn) {
        var names = turningOn
            ? ['restart_threshold', 'restart_temperature', 'on_threshold', 'on_temperature', 'threshold_value', 'target_temperature', 'threshold']
            : ['off_threshold', 'off_temperature', 'threshold_value', 'target_temperature', 'threshold'];
        return fmtEventTemp(valueFromEvent(e, names));
    }

    function currentTemperatureForHeaterEvent(e) {
        return fmtEventTemp(valueFromEvent(e, [
            'current_temperature', 'temperature', 'temperature_c', 'measured_temperature'
        ]));
    }

    function heaterEventContext(e, turningOn) {
        var parts = [];
        var temperature = currentTemperatureForHeaterEvent(e);
        var threshold = thresholdForHeaterEvent(e, turningOn);
        var mode = operatingMode(e);
        if (temperature) parts.push('Current temperature: ' + temperature);
        if (threshold) parts.push((turningOn ? 'Restart threshold: ' : 'Off threshold: ') + threshold);
        if (mode) parts.push('Mode: ' + mode);
        return parts.length ? ' ' + parts.join('. ') + '.' : '';
    }

    function tempFromTemperatureReached(e) {
        var direct = valueFromEvent(e, ['temperature', 'current_temperature', 'target_temperature', 'threshold_value', 'threshold']);
        if (direct !== null) return fmtEventTemp(direct);
        var msg = String((e && e.event_message) || '');
        var match = msg.match(/\((-?\d+(?:\.\d+)?)\s*(?:�C|C)?\)/i) || msg.match(/(-?\d+(?:\.\d+)?)\s*(?:�C|C)/i);
        return match ? fmtEventTemp(match[1]) : null;
    }

    function nearbyTemperatureThreshold(items, index) {
        if (!items) return null;
        var eventTime = new Date(items[index].created_at).getTime();
        var best = null;
        for (var distance = 1; distance <= 4; distance++) {
            var before = items[index - distance];
            var after = items[index + distance];
            [before, after].forEach(function (candidate) {
                if (!candidate || best) return;
                var type = String(candidate.event_type || '').toLowerCase().replace(/[\s-]+/g, '_');
                if (type !== 'temperature_reached' && type !== 'temperaturereached') return;
                var candidateTime = new Date(candidate.created_at).getTime();
                if (!isNaN(eventTime) && !isNaN(candidateTime) && Math.abs(candidateTime - eventTime) > 120000) return;
                best = tempFromTemperatureReached(candidate);
            });
            if (best) return best;
        }
        return null;
    }

    function hasNearbyRemoteEvent(items, index) {
        if (!items) return false;
        var eventTime = new Date(items[index].created_at).getTime();
        for (var distance = 1; distance <= 3; distance++) {
            var candidates = [items[index - distance], items[index + distance]];
            for (var i = 0; i < candidates.length; i++) {
                var candidate = candidates[i];
                if (!candidate) continue;
                var text = (String(candidate.event_type || '') + ' ' + String(candidate.event_message || '')).toLowerCase();
                if (text.indexOf('heater') === -1 || (text.indexOf('command') === -1 && text.indexOf('remote') === -1)) continue;
                var candidateTime = new Date(candidate.created_at).getTime();
                if (!isNaN(eventTime) && !isNaN(candidateTime) && Math.abs(candidateTime - eventTime) > 120000) continue;
                return true;
            }
        }
        return false;
    }

    function inferHeaterReason(e, turningOn, items, index) {
        var rawReason = valueFromEvent(e, ['trigger_source', 'reason', 'trigger', 'source', 'action_source', 'command_source']);
        var reason = normalizeReason(rawReason);
        var msg = String((e && e.event_message) || '').toLowerCase();
        if (!reason) {
            if (msg.indexOf('automatic') !== -1 || msg.indexOf('threshold') !== -1 || msg.indexOf('temperature') !== -1) reason = 'automatic';
            else if (msg.indexOf('manual') !== -1 || msg.indexOf('operator') !== -1) reason = 'manual';
            else if (msg.indexOf('remote') !== -1 || msg.indexOf('command') !== -1) reason = 'remote';
        }
        if (!reason && hasNearbyRemoteEvent(items, index)) reason = 'remote';
        if (!reason && (thresholdForHeaterEvent(e, turningOn) || nearbyTemperatureThreshold(items, index))) reason = 'automatic';
        return reason;
    }

    function heaterEventDetail(e, turningOn, items, index) {
        var reason = inferHeaterReason(e, turningOn, items, index);
        var threshold = thresholdForHeaterEvent(e, turningOn) || nearbyTemperatureThreshold(items, index);
        var context = heaterEventContext(e, turningOn);
        if (reason === 'automatic') {
            if (turningOn) {
                return threshold
                    ? 'Heater turned ON automatically because the temperature dropped below the restart threshold (' + threshold + ').' + context
                    : 'Heater turned ON automatically because the temperature dropped below the restart threshold.' + context;
            }
            return threshold
                ? 'Heater turned OFF automatically after reaching the off threshold (' + threshold + ').' + context
                : 'Heater turned OFF automatically after reaching the off threshold.' + context;
        }
        if (reason === 'manual') {
            return 'Heater turned ' + (turningOn ? 'ON' : 'OFF') + ' manually by the operator' +
                (operatingMode(e) ? ' while in ' + operatingMode(e) + ' mode.' : '.') + context;
        }
        if (reason === 'remote') {
            return 'Heater turned ' + (turningOn ? 'ON' : 'OFF') + ' by a remote dashboard command.' + context;
        }
        return 'Heater turned ' + (turningOn ? 'ON' : 'OFF') +
            '; trigger source and reason were not recorded for this legacy event.' + context;
    }

    function eventDetailsText(e, items, index) {
        var type = String((e && e.event_type) || '').toLowerCase().replace(/[\s-]+/g, '_');
        if (type === 'heater_on' || type === 'heateron') return heaterEventDetail(e, true, items, index);
        if (type === 'heater_off' || type === 'heateroff') return heaterEventDetail(e, false, items, index);
        return e.event_message || '-';
    }
    function renderEventRows(items) {
        var html = '<div class="table-responsive"><table class="table table-sm eidli-table-sm mb-0">';
        html += '<thead><tr><th>Time</th><th>Event</th><th>Details</th></tr></thead><tbody>';
        items.forEach(function (e, index) {
            html += '<tr>' +
                '<td class="text-nowrap">' + esc(fmtDateTime(e.created_at)) + '</td>' +
                '<td>' + esc(E.titleCase(e.event_type)) + '</td>' +
                '<td class="text-muted">' + esc(eventDetailsText(e, items, index)) + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    var eventsList = createList({
        url: URLS.events, bodyId: 'eidli-events-body', moreId: 'eidli-events-more',
        dateField: 'created_at', page: 50, cacheKey: 'events',
        emptyText: 'No machine events in the selected period.', errorText: 'Unable to load events.',
        renderRows: renderEventRows
    });

    // --- commands ------------------------------------------------------------------

    function renderCommandRows(items) {
        var html = '<div class="table-responsive"><table class="table table-sm eidli-table-sm mb-0">';
        html += '<thead><tr><th>Command</th><th>Requested</th><th>Status</th><th>Acknowledged</th><th>Response</th></tr></thead><tbody>';
        items.forEach(function (c) {
            html += '<tr>' +
                '<td>' + esc(E.titleCase(c.command)) + '</td>' +
                '<td class="text-nowrap">' + esc(fmtDateTime(c.requested_at)) + '</td>' +
                '<td>' + E.commandStatusBadge(c.status) + '</td>' +
                '<td class="text-nowrap">' + esc(fmtDateTime(c.ack_received_at)) + '</td>' +
                '<td class="text-muted">' + esc(c.response_message || '—') + '</td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    var commandsList = createList({
        url: URLS.commands, bodyId: 'eidli-commands-body', moreId: 'eidli-commands-more',
        dateField: 'requested_at', cacheKey: 'commands',
        emptyText: 'No commands sent during the selected period.', errorText: 'Unable to load command history.',
        renderRows: renderCommandRows
    });

    var LISTS = { events: eventsList, commands: commandsList };

    // --- tabs ------------------------------------------------------------------

    // Modules for tabs this file doesn't own (currently just the Analytics
    // graph, in history-analytics.js) register here to be notified whenever
    // their tab becomes active — same "first-visit lazy load" shape as
    // LISTS above, without this file needing to import or know anything
    // about what Analytics actually does.
    var tabActivateListeners = {};
    function onTabActivate(tab, fn) {
        (tabActivateListeners[tab] = tabActivateListeners[tab] || []).push(fn);
    }

    function activateTab(tab) {
        var t0 = performance.now();
        currentTab = tab;
        document.querySelectorAll('#eidli-hist-tabs .nav-link').forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-tab') === tab);
        });
        document.querySelectorAll('.eidli-hist-pane').forEach(function (p) {
            p.style.display = (p.getAttribute('data-pane') === tab) ? 'block' : 'none';
        });
        // Both lists are eager-loaded on page open now (see
        // DOMContentLoaded below), so this is normally already loaded by
        // the time a tab is actually clicked — the isLoaded() check plus
        // load()'s own in-flight guard make this a safe no-op fallback
        // rather than a real fetch trigger in the common case.
        var list = LISTS[tab];
        if (list && !list.isLoaded()) list.load(true);
        (tabActivateListeners[tab] || []).forEach(function (fn) { try { fn(); } catch (e) {} });
        console.debug('[history-timing] tab switch to', tab, 'DOM update took', (performance.now() - t0).toFixed(1), 'ms');
    }

    function initTabs() {
        var tabButtons = document.querySelectorAll('#eidli-hist-tabs .nav-link');
        tabButtons.forEach(function (b) {
            b.addEventListener('click', function () { activateTab(b.getAttribute('data-tab')); });
        });
        var validTabs = Array.prototype.map.call(tabButtons, function (b) { return b.getAttribute('data-tab'); });
        var requested = new URLSearchParams(window.location.search).get('tab');
        activateTab((requested && validTabs.indexOf(requested) !== -1) ? requested : 'events');
    }

    // --- date range --------------------------------------------------------------

    // Notified after every successful applyDateRange()/clearDateRange() —
    // lets other modules on this page (history-analytics.js's Machine
    // Analytics graph) stay in sync with the one shared Events/Commands
    // range without this file needing to know anything about them. Fires
    // with the same {fromDate, toDate, fromTime, toTime, startISO, endISO}
    // shape every time, including on Clear (all fields null).
    var rangeChangeListeners = [];
    function onRangeChange(fn) { rangeChangeListeners.push(fn); }
    function notifyRangeChange() {
        var payload = { fromDate: null, toDate: null, fromTime: null, toTime: null, startISO: rangeStartISO, endISO: rangeEndISO };
        var fd = el('eidli-hist-from-date'), td = el('eidli-hist-to-date');
        if (fd) payload.fromDate = fd.value || null;
        if (td) payload.toDate = td.value || null;
        var ft = el('eidli-hist-from-time'), tt = el('eidli-hist-to-time');
        if (ft) payload.fromTime = ft.value || null;
        if (tt) payload.toTime = tt.value || null;
        rangeChangeListeners.forEach(function (fn) { try { fn(payload); } catch (e) {} });
    }

    // From cannot be after To (by date, or by time when dates are equal).
    // Returns an error string, or null when the range is valid. Both dates
    // are optional (an unset date means "no bound on this side") — only
    // checked against each other when BOTH are actually set.
    function validateDateRange(fromDate, toDate, fromTime, toTime) {
        if (!fromDate || !toDate) return null;
        if (fromDate > toDate) return 'The From date cannot be after the To date.';
        if (fromDate === toDate && fromTime && toTime && fromTime > toTime) {
            return 'The From time cannot be after the To time on the same day.';
        }
        return null;
    }

    // From/To are each a date + an optional time. Time defaults to the edge
    // of the day (00:00 for From, 23:59 for To) so picking dates alone
    // covers the entire day(s) — entering a specific time narrows the
    // filter down to that exact cutoff instead.
    function applyDateRange() {
        if (applyInFlight) return;

        var fromDate = el('eidli-hist-from-date').value;
        var toDate = el('eidli-hist-to-date').value;
        var fromTime = el('eidli-hist-from-time').value || '00:00';
        var toTime = el('eidli-hist-to-time').value || '23:59';

        var rangeErrorEl = el('eidli-hist-range-error');
        var validationError = validateDateRange(fromDate, toDate, fromTime, toTime);
        if (validationError) {
            // Invalid input never reaches the network — surfaced inline
            // right under the controls, not as a toast (toasts are for
            // transient events; this stays visible until corrected).
            if (rangeErrorEl) { rangeErrorEl.textContent = validationError; rangeErrorEl.style.display = 'block'; }
            return;
        }
        if (rangeErrorEl) rangeErrorEl.style.display = 'none';

        // If the fields no longer match the currently-highlighted preset's
        // own computed dates (the operator hand-edited a date after
        // clicking one, then hit Apply directly), the highlight would be
        // actively misleading — clear it rather than leave a stale
        // "Yesterday" lit up over dates that aren't actually Yesterday.
        var highlighted = document.querySelector('.eidli-date-preset.btn-success');
        if (highlighted) {
            var now = new Date();
            var p = highlighted.getAttribute('data-preset');
            var expectedFrom = E.istDateISO(now), expectedTo = E.istDateISO(now);
            if (p === 'yesterday') {
                var y = E.istDateISO(new Date(now.getTime() - ONE_DAY_MS));
                expectedFrom = y; expectedTo = y;
            } else if (p === 'week') {
                expectedFrom = E.istDateISO(new Date(now.getTime() - 6 * ONE_DAY_MS));
            } else if (p === 'month') {
                expectedFrom = E.istDateISO(new Date(now.getTime() - 29 * ONE_DAY_MS));
            } else if (p === 'custom') {
                expectedFrom = null; // Custom has no single computed answer to compare against — never auto-cleared
            }
            if (expectedFrom !== null && (fromDate !== expectedFrom || toDate !== expectedTo || fromTime !== '00:00' || toTime !== '23:59')) {
                highlightDatePreset(null);
            }
        }

        dateFromTs = fromDate ? new Date(fromDate + 'T' + fromTime + ':00').getTime() : null;
        dateToTs = toDate ? new Date(toDate + 'T' + toTime + ':59.999').getTime() : null;
        // IST-explicit ISO-8601 for the outgoing start_time/end_time query
        // params — matches the exact format the backend requires
        // (2026-08-04T00:00:00+05:30 / 2026-08-04T23:59:59.999999+05:30).
        rangeStartISO = fromDate ? (fromDate + 'T' + fromTime + ':00+05:30') : null;
        rangeEndISO = toDate ? (toDate + 'T' + toTime + ':59.999999+05:30') : null;

        // Every History section refetches immediately and in parallel —
        // Events and Commands — so "Yesterday" applies everywhere at once,
        // not just to whichever tab happens to be on screen right now. Tabs
        // not currently visible still update their data in the background;
        // activateTab()'s own isLoaded() check just finds them already
        // fresh whenever the user switches to one.
        var applyBtn = el('eidli-hist-apply');
        var originalLabel = applyBtn.textContent;
        applyInFlight = true;
        applyBtn.disabled = true;
        applyBtn.textContent = 'Applying…';
        // Deliberately does NOT blank any tab's table/body here — previous
        // data stays visible exactly as it is until each fresh response
        // actually arrives; createList.render() only replaces the DOM once
        // it has real new content to show, so there is no "blank while
        // loading" moment for any section.

        var listPromises = Object.keys(LISTS).map(function (k) { return LISTS[k].load(true); });

        // Fired immediately (not gated behind the Events/Commands promises
        // above) — the Analytics graph is a completely independent
        // consumer of this same range and must start loading right away,
        // not wait on unrelated tables it doesn't depend on.
        notifyRangeChange();

        Promise.all(listPromises).then(function (results) {
            applyInFlight = false;
            applyBtn.disabled = false;
            applyBtn.textContent = originalLabel;
            if (results.indexOf(false) !== -1) window.showToast('danger', 'Failed to load filtered data for one or more sections. Please try again.');
        });
    }


    function highlightDatePreset(preset) {
        document.querySelectorAll('.eidli-date-preset').forEach(function (btn) {
            var active = preset != null && btn.getAttribute('data-preset') === preset;
            btn.classList.toggle('btn-success', active);
            btn.classList.toggle('btn-outline-secondary', !active);
        });
    }

    function clearDateRange() {
        el('eidli-hist-from-date').value = ''; el('eidli-hist-from-time').value = '00:00';
        el('eidli-hist-to-date').value = ''; el('eidli-hist-to-time').value = '23:59';
        var rangeErrorEl = el('eidli-hist-range-error');
        if (rangeErrorEl) rangeErrorEl.style.display = 'none';
        highlightDatePreset(null);
        applyDateRange();
    }

    // Today/Yesterday/Last-7-Days/Last-30-Days need the IST calendar date,
    // not whatever date it happens to be in the viewer's own browser
    // timezone — reuses core.js's istDateISO() (built on the same IST_TZ
    // constant every other timestamp on this app is already formatted
    // with) rather than a second, separate timezone calculation. IST has no
    // DST, so subtracting a fixed number of 24h days from `now` and reading
    // its IST calendar date is exact — there's no daylight-saving edge case
    // to account for.
    var ONE_DAY_MS = 24 * 60 * 60 * 1000;

    function initDateControls() {
        el('eidli-hist-apply').addEventListener('click', applyDateRange);
        el('eidli-hist-clear').addEventListener('click', clearDateRange);
        document.querySelectorAll('.eidli-date-preset').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var p = btn.getAttribute('data-preset');
                // Custom Range only highlights the button and leaves the
                // From/To fields exactly as they are (the operator picks
                // their own dates then hits Apply) — there's nothing valid
                // to auto-compute or fetch until real dates are chosen.
                if (p === 'custom') {
                    highlightDatePreset('custom');
                    var rangeErrorEl = el('eidli-hist-range-error');
                    if (rangeErrorEl) rangeErrorEl.style.display = 'none';
                    return;
                }
                var now = new Date();
                var fromStr = E.istDateISO(now), toStr = E.istDateISO(now);
                if (p === 'yesterday') {
                    var yesterday = E.istDateISO(new Date(now.getTime() - ONE_DAY_MS));
                    fromStr = yesterday; toStr = yesterday;
                } else if (p === 'week') {
                    fromStr = E.istDateISO(new Date(now.getTime() - 6 * ONE_DAY_MS));
                } else if (p === 'month') {
                    fromStr = E.istDateISO(new Date(now.getTime() - 29 * ONE_DAY_MS));
                }
                el('eidli-hist-from-date').value = fromStr;
                el('eidli-hist-from-time').value = '00:00';
                el('eidli-hist-to-date').value = toStr;
                el('eidli-hist-to-time').value = '23:59';
                // Stays highlighted through Apply and every subsequent tab
                // switch — nothing else in activateTab() touches these
                // buttons, so this persists until a different preset is
                // clicked or Clear resets it.
                highlightDatePreset(p);
                applyDateRange();
            });
        });
    }

    // --- refresh buttons -----------------------------------------------------------

    function initRefreshAndMore() {
        el('eidli-events-refresh').addEventListener('click', function () { eventsList.load(true); });
        el('eidli-events-more').addEventListener('click', function () { eventsList.load(false); });
        el('eidli-commands-refresh').addEventListener('click', function () { commandsList.load(true); });
        el('eidli-commands-more').addEventListener('click', function () { commandsList.load(false); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        E.startHeader();
        initDateControls();
        initRefreshAndMore();
        if (!CONFIGURED) {
            Object.keys(LISTS).forEach(function (k) { el('eidli-' + k + '-body').innerHTML = '<div class="eidli-section-empty">Not connected.</div>'; });
            return;
        }
        // Instant paint from whatever was cached the last time this page
        // was open in this tab — before initTabs()/activateTab() runs and
        // before any of the eager loads below have even been dispatched.
        Object.keys(LISTS).forEach(function (k) { LISTS[k].hydrate(); });

        initTabs();

        // Both lists load in parallel up front now, instead of lazily
        // per tab click — so every subsequent tab switch (Events <->
        // Commands) is instant: no fetch, no spinner, data's already there.
        // initTabs()'s activateTab() call above may
        // have already started loading the initial tab; load()'s own
        // in-flight guard makes sure that doesn't turn into a duplicate
        // request for the same tab.
        Object.keys(LISTS).forEach(function (k) { LISTS[k].load(true); });

        // Events/Commands now refresh automatically too — whichever tab is
        // actually on screen, so anything happening elsewhere shows up here
        // without a reload.
        setInterval(function () {
            if (document.visibilityState !== 'visible') return;
            var list = LISTS[currentTab];
            if (list) list.load(true);
        }, HISTORY_AUTO_REFRESH_MS);
    });

    // Small public surface for history-analytics.js (the Machine Analytics
    // graph) to share this same page-level date range instead of running
    // its own separate copy of the preset/validation logic. Nothing else on
    // this page reads window.EidliHistory — Events/Commands are untouched.
    window.EidliHistory = {
        onRangeChange: onRangeChange,
        getRange: function () {
            var fd = el('eidli-hist-from-date'), td = el('eidli-hist-to-date');
            var ft = el('eidli-hist-from-time'), tt = el('eidli-hist-to-time');
            return {
                fromDate: fd ? (fd.value || null) : null, toDate: td ? (td.value || null) : null,
                fromTime: ft ? (ft.value || null) : null, toTime: tt ? (tt.value || null) : null,
                startISO: rangeStartISO, endISO: rangeEndISO
            };
        },
        onTabActivate: onTabActivate
    };
})();
