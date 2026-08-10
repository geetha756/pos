/*
 * Electric Idli Machine — History page (Sessions / Heating Cycles / Events /
 * Commands). An investigation/audit workspace, not the live-ops view.
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
    var fmtTemp = E.fmtTemp, fmtTime = E.fmtTime, fmtDateTime = E.fmtDateTime, fmtDuration = E.fmtDuration, fmtDate = E.fmtDate;
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
    var currentTab = 'sessions';
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

    // --- sessions --------------------------------------------------------------

    function renderSessionRows(items) {
        var html = '<div class="table-responsive"><table class="table table-sm eidli-table-sm mb-0">';
        html += '<thead><tr><th>Session</th><th>Started</th><th>Ended</th><th>Duration</th><th>Start</th><th>Target</th><th>Max</th><th>Cycles</th><th>Status</th><th>End Reason</th><th></th></tr></thead><tbody>';
        items.forEach(function (s) {
            html += '<tr>' +
                '<td>#' + esc(s.session_number) + '</td>' +
                '<td class="text-nowrap">' + esc(fmtDateTime(s.started_at)) + '</td>' +
                '<td class="text-nowrap">' + esc(fmtDateTime(s.completed_at)) + '</td>' +
                '<td>' + fmtDuration(s.duration_seconds) + '</td>' +
                '<td>' + fmtTemp(s.start_temperature) + '</td>' +
                '<td>' + fmtTemp(s.target_temperature) + '</td>' +
                '<td>' + fmtTemp(s.max_temperature) + '</td>' +
                '<td>' + (s.heating_cycle_count != null ? s.heating_cycle_count : '—') + '</td>' +
                '<td>' + E.sessionStatusBadge(s.status) + '</td>' +
                '<td class="text-muted">' + esc(s.end_reason || '—') + '</td>' +
                '<td><button type="button" class="btn btn-sm btn-outline-secondary eidli-view-session-btn" data-session-id="' + esc(s.id) + '">View</button></td>' +
                '</tr>';
        });
        html += '</tbody></table></div>';
        return html;
    }

    var sessionsList = createList({
        url: URLS.sessions, bodyId: 'eidli-sessions-body', moreId: 'eidli-sessions-more',
        statusSelectId: 'eidli-sessions-status', dateField: 'started_at', cacheKey: 'sessions',
        emptyText: 'No cooking sessions yet.', errorText: 'Unable to load session history.',
        renderRows: renderSessionRows,
        afterRender: function (body) {
            Array.prototype.forEach.call(body.querySelectorAll('.eidli-view-session-btn'), function (btn) {
                btn.addEventListener('click', function () { openSessionDetail(btn.getAttribute('data-session-id')); });
            });
        }
    });

    function sessionNumberById(id) {
        if (!id) return null;
        var m = sessionsList.getItems().filter(function (s) { return s.id === id; })[0];
        return m ? m.session_number : null;
    }

    // --- machine runtime analytics ------------------------------------------------
    //
    // Daily total runtime = sum of duration_seconds across completed cooking
    // sessions that started on that IST calendar day. This is computed
    // entirely from the sessions the backend already returns (started_at,
    // duration_seconds, status) — no dedicated backend endpoint exists or is
    // needed. It's a separate, dedicated fetch (not reusing sessionsList's
    // items) because its own Yesterday/Last-7-Days window can reach further
    // back than whatever the Sessions table happens to have paginated in,
    // and can disagree with the shared date-range filter above.
    var RUNTIME_PAGE = 200;
    var RUNTIME_MAX_PAGES = 20; // safety cap — 4,000 sessions is far more than any real 7-day window
    // "completed" alone is too narrow on real data — this machine rarely
    // finishes a cook naturally; most sessions end via manual stop or a
    // connectivity drop, so a strict status==='completed' filter would zero
    // out most bars. duration_seconds is meaningful for every status,
    // 'active' included: per the backend contract it's "seconds since
    // started_at, or the final duration once ended" — for an active
    // session that's its live, still-growing elapsed time, and it's real,
    // ongoing runtime (the active status itself confirms the machine is
    // genuinely still cooking right now, unlike a long-interrupted session
    // where a dead connection can't be told apart from a real multi-hour
    // cook). So every status below contributes its duration; only
    // interrupted/faulted get capped (see RUNTIME_UNRELIABLE_STATUSES) —
    // active is deliberately NOT in that list.
    var RUNTIME_INCLUDED_STATUSES = ['completed', 'stopped', 'interrupted', 'faulted', 'active'];
    // 'completed' and 'stopped' have a trustworthy duration_seconds — the
    // session ended because the cook finished or the operator pressed stop,
    // so elapsed time IS cooking time.
    //
    // 'interrupted'/'faulted' don't: duration_seconds there is wall-clock
    // time until the backend's offline-detector noticed the machine was
    // gone (see end_reason: "no telemetry received within 15s"), which can
    // run for minutes (a real, short cook cut off by a network blip — still
    // legitimate runtime) or for many hours (the machine was simply powered
    // off/unreachable, e.g. session #5 clocking ~42h). There's no reliable
    // signal in the payload to tell those two apart, so instead of an
    // all-or-nothing include/exclude, cap the counted duration at a ceiling
    // that a real unattended idli cook would never plausibly exceed. Short
    // interrupted sessions still count their real (short) duration in full;
    // only the long tail — almost certainly outage time, not cooking time —
    // gets clamped. Adjust the ceiling here if 4h proves too generous/strict.
    var RUNTIME_UNRELIABLE_STATUSES = ['interrupted', 'faulted'];
    var RUNTIME_UNRELIABLE_CAP_SECONDS = 4 * 60 * 60;
    var RUNTIME_HOURS = [];
    for (var _rh = 0; _rh < 24; _rh++) RUNTIME_HOURS.push(_rh);

    var runtimeChart = null;
    var runtimeFetchInFlight = false;
    // Bar vs. Line is purely a rendering choice over data that's already in
    // hand — runtimeLastResult holds the last fetch's aggregated result so
    // toggling type re-renders instantly with zero new API calls.
    // runtimeTooltipSeconds is read by the tooltip callback below, which is
    // only ever defined once (at first chart construction); keeping it as a
    // shared mutable array that render updates in place means the callback
    // stays valid across every subsequent re-render without being redefined.
    var runtimeChartType = 'bar';
    var runtimeLastResult = null;
    var runtimeTooltipSeconds = [];
    // Refetches while an active session's duration_seconds is climbing —
    // only runs while the Runtime tab is actually the one on screen, so
    // this history/audit page isn't silently polling in the background
    // when the operator is looking at Sessions/Cycles/Events/Commands.
    var RUNTIME_AUTO_REFRESH_MS = 5000;
    var runtimeAutoRefreshTimer = null;

    function startRuntimeAutoRefresh() {
        if (runtimeAutoRefreshTimer) return;
        runtimeAutoRefreshTimer = setInterval(function () {
            if (document.visibilityState === 'visible') fetchRuntimeAnalytics();
        }, RUNTIME_AUTO_REFRESH_MS);
    }

    function stopRuntimeAutoRefresh() {
        if (runtimeAutoRefreshTimer) { clearInterval(runtimeAutoRefreshTimer); runtimeAutoRefreshTimer = null; }
    }

    // Day-bucket list driven by the SHARED History date filter
    // (dateFromTs/dateToTs — the same state Sessions/Cycles/Events/Commands
    // use) instead of a separate range of its own, so Runtime Analytics
    // can't disagree with the rest of the page about what's currently
    // applied. Falls back to "today" when nothing's been applied yet
    // (both null — the page's initial state before any Apply/Clear).
    function computeRuntimeRangeDays() {
        if (!dateFromTs || !dateToTs) return [E.istDateISO(new Date())];
        var fromDay = E.istDateISO(new Date(dateFromTs));
        var toDay = E.istDateISO(new Date(dateToTs));
        var days = [];
        var cursorTs = new Date(fromDay + 'T00:00:00+05:30').getTime();
        var endTs = new Date(toDay + 'T00:00:00+05:30').getTime();
        var guard = 0; // safety cap matching the rest of this app's pattern — a date-range filter shouldn't ever produce an unbounded walk
        while (cursorTs <= endTs && guard < 366) {
            days.push(E.istDateISO(new Date(cursorTs)));
            cursorTs += ONE_DAY_MS;
            guard++;
        }
        return days;
    }

    // Hour-of-day (0-23) in Asia/Kolkata — the same IST convention
    // istDateISO() already uses elsewhere in this file — needed to bucket
    // Today/Yesterday's sessions across the day instead of into one total.
    function istHourOfDay(date) {
        return Number(new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Kolkata', hour: 'numeric', hourCycle: 'h23' }).format(date));
    }

    function fmtHoursMinutes(totalSeconds) {
        var totalMinutes = Math.round(totalSeconds / 60);
        var h = Math.floor(totalMinutes / 60), m = totalMinutes % 60;
        return h > 0 ? (h + 'h ' + m + 'm') : (m + 'm');
    }

    // IST is a fixed +5:30 offset (no DST), so "the start of the next IST
    // hour/day after this instant" can be computed directly in UTC ms
    // without needing a timezone library: shift into IST-local ms, floor to
    // the bucket size, shift back.
    var IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
    function nextIstBoundaryMs(ms, bucketMs) {
        var istLocalMs = ms + IST_OFFSET_MS;
        var bucketStartIstLocalMs = Math.floor(istLocalMs / bucketMs) * bucketMs;
        return (bucketStartIstLocalMs + bucketMs) - IST_OFFSET_MS;
    }

    // Splits one session's duration across every hour/day bucket it
    // actually overlaps, instead of dumping the whole thing into whichever
    // bucket contains started_at — a 3h7m session starting at 10:00 must
    // show ~53m in the 10:00 bar, 1h each in 11:00/12:00, and the remaining
    // ~7m in 13:00, not the full 3h7m crammed into 10:00 alone (which is
    // nonsensical for a 60-minute-wide bucket and, combined with whatever
    // other real sessions happen to land in the following hours, creates
    // exactly the "still looks like it's running" illusion this fixes).
    // Segments landing outside the applied day-range are dropped rather
    // than counted (matches how every other History tab strictly scopes to
    // the applied range) — returns how many seconds actually landed inside
    // the range, so callers can use it for accurate per-session summary
    // totals instead of the session's full (possibly out-of-range-spilling)
    // duration.
    function splitSessionIntoBuckets(startedAtMs, totalSeconds, granularity, singleDay, totals) {
        var endMs = startedAtMs + totalSeconds * 1000;
        var cursorMs = startedAtMs;
        var bucketMs = granularity === 'hour' ? (60 * 60 * 1000) : (24 * 60 * 60 * 1000);
        var counted = 0;
        var guard = 0; // safety cap — bounded by totalSeconds/bucketMs in practice, this just prevents any unforeseen edge case from looping forever
        while (cursorMs < endMs && guard < 400) {
            var boundaryMs = nextIstBoundaryMs(cursorMs, bucketMs);
            var segmentEndMs = Math.min(endMs, boundaryMs);
            var segmentSeconds = (segmentEndMs - cursorMs) / 1000;
            var cursorDate = new Date(cursorMs);
            var day = E.istDateISO(cursorDate);
            if (granularity === 'hour') {
                if (day === singleDay) { totals[istHourOfDay(cursorDate)] += segmentSeconds; counted += segmentSeconds; }
            } else if (totals.hasOwnProperty(day)) {
                totals[day] += segmentSeconds; counted += segmentSeconds;
            }
            cursorMs = segmentEndMs;
            guard++;
        }
        return counted;
    }

    function finishRuntimeFetch(sessions, days) {
        runtimeFetchInFlight = false;
        el('eidli-runtime-loading').style.display = 'none';

        console.debug('[runtime-analytics] days in range:', days);
        console.debug('[runtime-analytics] total sessions fetched:', sessions.length, sessions);

        var ended = sessions.filter(function (s) { return RUNTIME_INCLUDED_STATUSES.indexOf((s.status || '').toLowerCase()) !== -1; });
        console.debug('[runtime-analytics] sessions with an included status', RUNTIME_INCLUDED_STATUSES, '->', ended.length,
            ended.map(function (s) { return { id: s.id, status: s.status, started_at: s.started_at, duration_seconds: s.duration_seconds }; }));

        // A single-day applied range (Today/Yesterday, or a Custom range
        // where From === To) shows a within-day trend (hourly buckets)
        // instead of one collapsed total; any multi-day range keeps the
        // original one-bucket-per-day aggregation. This only changes which
        // bucket a session's duration lands in — the per-session
        // include/cap logic above and below is byte-for-byte the same
        // regardless of granularity.
        var granularity = (days.length === 1) ? 'hour' : 'day';
        var singleDay = granularity === 'hour' ? days[0] : null;
        var bucketKeys = granularity === 'day' ? days : RUNTIME_HOURS;

        var totals = {};
        bucketKeys.forEach(function (k) { totals[k] = 0; });

        var included = []; // one entry per session actually counted here — feeds the summary cards
        ended.forEach(function (s) {
            if (s.duration_seconds == null || !s.started_at) return;
            var day = E.istDateISO(new Date(s.started_at));
            // Inclusion is still based on the session's START day (a session
            // starting entirely outside the applied range doesn't count at
            // all) — only how its OWN duration gets distributed across
            // buckets changed. Widening this to also include sessions that
            // merely overlap the range from before it started is a separate
            // question, not what was reported here, so left alone.
            if (granularity === 'day' && !totals.hasOwnProperty(day)) return;
            if (granularity === 'hour' && day !== singleDay) return;

            var status = (s.status || '').toLowerCase();
            var seconds = Number(s.duration_seconds);
            if (RUNTIME_UNRELIABLE_STATUSES.indexOf(status) !== -1 && seconds > RUNTIME_UNRELIABLE_CAP_SECONDS) {
                console.debug('[runtime-analytics] capping', status, 'session', s.id, '-', seconds, 's ->', RUNTIME_UNRELIABLE_CAP_SECONDS, 's (likely outage time, not cooking time)');
                seconds = RUNTIME_UNRELIABLE_CAP_SECONDS;
            }

            var startedAtMs = new Date(s.started_at).getTime();
            var countedSeconds = splitSessionIntoBuckets(startedAtMs, seconds, granularity, singleDay, totals);
            included.push({ seconds: countedSeconds, sessionNumber: s.session_number });
        });
        console.debug('[runtime-analytics] grouped totals (seconds) by', granularity, ':', totals);

        var buckets = bucketKeys.map(function (k) { return { key: k, seconds: totals[k] }; });
        renderRuntimeAnalytics({ granularity: granularity, buckets: buckets, included: included });
    }

    // Returns a Promise<boolean> (mirrors dashboard.js's fetchChartData) so
    // applyDateRange() can await this alongside the active tab's list load
    // and give consistent Apply-button feedback regardless of which tab is
    // actually on screen when Apply is clicked.
    //
    // Uses the backend's start_time/end_time filtering (same contract the
    // four lists' createList.load() already uses) instead of the old
    // "walk pages backward from offset 0 until past the range start"
    // approach — that approach assumed the range always extended through
    // "now" (fine when this had its own Today/Yesterday/7-days-only
    // control); now that it shares the page's full filter (which can be
    // Last 30 Days or an arbitrary Custom range entirely in the past), a
    // server-side filter is both correct and far more efficient than
    // walking through potentially-irrelevant newer pages first.
    function fetchRuntimeAnalytics() {
        if (!CONFIGURED || runtimeFetchInFlight) return Promise.resolve(false);
        runtimeFetchInFlight = true;
        el('eidli-runtime-error').style.display = 'none';
        el('eidli-runtime-loading').style.display = 'block';

        var days = computeRuntimeRangeDays();
        var startISO = days[0] + 'T00:00:00+05:30';
        var endISO = days[days.length - 1] + 'T23:59:59.999999+05:30';
        var collected = [], offset = 0, pages = 0;

        return new Promise(function (resolve) {
            function fail() {
                runtimeFetchInFlight = false;
                el('eidli-runtime-loading').style.display = 'none';
                el('eidli-runtime-error').style.display = 'block';
                resolve(false);
            }

            function nextPage() {
                pages++;
                var url = URLS.sessions + '?limit=' + RUNTIME_PAGE + '&offset=' + offset +
                    '&start_time=' + encodeURIComponent(startISO) + '&end_time=' + encodeURIComponent(endISO);
                apiFetch(url).then(function (res) {
                    if (!res.ok || !res.body.success) { fail(); return; }
                    var data = res.body.data || {};
                    var newItems = data.items || [];
                    var total = data.total || 0;
                    console.debug('[runtime-analytics] fetched page', pages, '-', newItems.length, 'of', total, 'total sessions in range, raw:', newItems);
                    collected = collected.concat(newItems);
                    offset += newItems.length;

                    var exhausted = !newItems.length || offset >= total;
                    if (exhausted || pages >= RUNTIME_MAX_PAGES) {
                        finishRuntimeFetch(collected, days);
                        resolve(true);
                    } else {
                        nextPage();
                    }
                }).catch(fail);
            }
            nextPage();
        });
    }

    function updateRuntimeSummaryCards(included) {
        var totalSeconds = included.reduce(function (sum, i) { return sum + i.seconds; }, 0);
        var count = included.length;
        var avgSeconds = count ? totalSeconds / count : 0;
        var longestSeconds = included.reduce(function (max, i) { return Math.max(max, i.seconds); }, 0);

        el('eidli-runtime-total').textContent = fmtHoursMinutes(totalSeconds);
        el('eidli-runtime-count').textContent = String(count);
        el('eidli-runtime-avg').textContent = fmtHoursMinutes(avgSeconds);
        el('eidli-runtime-longest').textContent = fmtHoursMinutes(longestSeconds);
    }

    // Bar-specific (backgroundColor/borderRadius/spacing) vs. line-specific
    // (borderColor/tension/gradient fill/markers) dataset keys — the X/Y
    // data, scales, tooltip, and colour (#157a5e, same in both) never
    // change; only how Chart.js draws that same data differs.
    function buildRuntimeDataset(type, minutes) {
        var BAR = '#157a5e';
        if (type === 'line') {
            return {
                label: 'Runtime', data: minutes,
                borderColor: BAR, borderWidth: 3, tension: 0.35,
                pointStyle: 'circle', pointRadius: 4, pointHoverRadius: 6,
                pointBackgroundColor: BAR, pointBorderColor: '#fff', pointBorderWidth: 2,
                fill: true,
                backgroundColor: function (context) {
                    var chartArea = context.chart.chartArea;
                    if (!chartArea) return null;
                    var ctx = context.chart.ctx;
                    var gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
                    gradient.addColorStop(0, 'rgba(21, 122, 94, 0.35)');
                    gradient.addColorStop(1, 'rgba(21, 122, 94, 0)');
                    return gradient;
                }
            };
        }
        return { label: 'Runtime', data: minutes, backgroundColor: BAR, borderRadius: 6, borderSkipped: false, maxBarThickness: 46, categoryPercentage: 0.7, barPercentage: 0.85 };
    }

    // Splits fetch-driven updates (recompute summary cards + decide
    // empty-vs-chart) from pure rendering (renderRuntimeChart below), so a
    // chart-type toggle can call the latter directly on cached data without
    // re-touching the summary cards or re-fetching anything.
    function renderRuntimeAnalytics(result) {
        runtimeLastResult = result;
        try { sessionStorage.setItem('eidli_hist_cache_runtime', JSON.stringify(result)); } catch (e) {}
        updateRuntimeSummaryCards(result.included);

        var hasData = result.included.length > 0;
        el('eidli-runtime-empty').style.display = hasData ? 'none' : 'block';
        el('eidli-runtime-chart-wrap').style.display = hasData ? 'block' : 'none';
        if (!hasData) {
            if (runtimeChart) { runtimeChart.destroy(); runtimeChart = null; }
            return;
        }
        renderRuntimeChart(result);
    }

    // Paints the last cached Runtime Analytics result instantly on page
    // open, before fetchRuntimeAnalytics()'s real (and, per the measured
    // /sessions latency, meaningfully slow) fetch even starts — same
    // stale-then-fresh pattern as the four lists' hydrate() above.
    function hydrateRuntimeFromCache() {
        try {
            var cached = sessionStorage.getItem('eidli_hist_cache_runtime');
            if (cached) renderRuntimeAnalytics(JSON.parse(cached));
        } catch (e) {}
    }

    function renderRuntimeChart(result) {
        if (typeof Chart === 'undefined') return;

        var labels = result.buckets.map(function (b) {
            return result.granularity === 'day' ? fmtDate(b.key + 'T00:00:00+05:30') : (String(b.key).padStart(2, '0') + ':00');
        });
        var minutes = result.buckets.map(function (b) { return Math.round(b.seconds / 60); });
        runtimeTooltipSeconds = result.buckets.map(function (b) { return b.seconds; });

        var dataset = buildRuntimeDataset(runtimeChartType, minutes);

        // Switching Bar <-> Line reuses the live Chart.js instance — mutate
        // config.type + data and call update() (Chart.js v4 supports this
        // directly) instead of destroy()/recreate. No API call either way:
        // this path runs both on a fresh fetch and on a pure type toggle.
        if (runtimeChart) {
            runtimeChart.config.type = runtimeChartType;
            runtimeChart.data.labels = labels;
            runtimeChart.data.datasets = [dataset];
            runtimeChart.update();
            return;
        }

        var INK = '#6b7280', GRID = '#e5e7eb';
        runtimeChart = new Chart(el('eidli-runtime-chart'), {
            type: runtimeChartType,
            data: { labels: labels, datasets: [dataset] },
            options: {
                responsive: true, maintainAspectRatio: false,
                // No "grow in" animation on (re)draw — keeps refreshes snappy
                // — but hover still gets a smooth transition (point/bar
                // highlight), set separately via transitions.active.
                animation: { duration: 0 },
                transitions: { active: { animation: { duration: 200 } } },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: function (items) { return items[0].label; },
                            label: function (ctx) { return 'Runtime: ' + fmtHoursMinutes(runtimeTooltipSeconds[ctx.dataIndex]); }
                        }
                    }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: INK, font: { size: 10 } } },
                    y: {
                        beginAtZero: true,
                        grid: { color: GRID },
                        ticks: { color: INK, callback: function (v) { return fmtHoursMinutes(v * 60); } }
                    }
                }
            }
        });
    }

    function selectRuntimeChartType(type) {
        if (type === runtimeChartType) return;
        runtimeChartType = type;
        document.querySelectorAll('#eidli-runtime-type-group button').forEach(function (b) {
            var active = b.getAttribute('data-runtime-type') === type;
            b.classList.toggle('btn-success', active);
            b.classList.toggle('btn-outline-secondary', !active);
        });
        if (runtimeLastResult && runtimeLastResult.included.length > 0) renderRuntimeChart(runtimeLastResult);
    }

    function initRuntimeAnalytics() {
        document.querySelectorAll('#eidli-runtime-type-group button').forEach(function (b) {
            b.addEventListener('click', function () { selectRuntimeChartType(b.getAttribute('data-runtime-type')); });
        });
    }

    // --- heating cycles ----------------------------------------------------------

    function cycleStep(label, time, temp, reached, terminal) {
        var cls = reached ? '' : (terminal ? 'text-muted' : 'text-muted fst-italic');
        var timeText = reached ? fmtTime(time) : (terminal ? 'Not reached' : 'Pending');
        return '<div class="text-center px-2">' +
            '<div class="small fw-semibold ' + cls + '">' + esc(label) + '</div>' +
            '<div class="small ' + cls + '">' + fmtTemp(temp) + '</div>' +
            '<div class="small text-muted">' + esc(timeText) + '</div>' +
            '</div>';
    }

    function renderCycleCard(c) {
        var sessionNum = sessionNumberById(c.cooking_session_id);
        var sessionLabel = c.cooking_session_id ? (sessionNum ? 'Session #' + sessionNum : 'Session') : 'Outside a cooking session';
        var isAbandoned = (c.status || '').toLowerCase() === 'abandoned';
        var reachedOff = !!c.heater_off_at, reachedRestart = !!c.heater_restart_at;

        var html = '<div class="border rounded p-3 mb-2" style="border-color: var(--eidli-border) !important;' + (isAbandoned ? 'border-color: var(--eidli-bad) !important;' : '') + '">';
        html += '<div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">';
        html += '<div><span class="fw-semibold">Cycle #' + esc(c.cycle_number) + '</span> ' + E.cycleStatusBadge(c.status) + '</div>';
        html += '<div class="text-muted small">' + esc(sessionLabel) + '</div></div>';
        html += '<div class="d-flex align-items-start flex-wrap">';
        html += cycleStep('Started', c.heater_on_at, c.start_temperature, true, false);
        html += '<div class="text-muted px-1 pt-2">→</div>';
        html += cycleStep('Heater Off', c.heater_off_at, c.peak_temperature, reachedOff, isAbandoned && !reachedOff);
        html += '<div class="text-muted px-1 pt-2">→</div>';
        html += cycleStep('Restarted', c.heater_restart_at, c.restart_temperature, reachedRestart, isAbandoned && !reachedRestart);
        html += '</div>';
        var footer = [];
        if (c.duration_seconds != null) footer.push('Duration: ' + fmtDuration(c.duration_seconds));
        if (isAbandoned) footer.push('<span style="color:var(--eidli-bad);">Abandoned — the machine went offline or the session ended before this cycle finished.</span>');
        if (footer.length) html += '<div class="small text-muted mt-2 pt-2 border-top" style="border-color: var(--eidli-border) !important;">' + footer.join(' · ') + '</div>';
        html += '</div>';
        return html;
    }

    var cyclesList = createList({
        url: URLS.heatingCycles, bodyId: 'eidli-cycles-body', moreId: 'eidli-cycles-more',
        statusSelectId: 'eidli-cycles-status', dateField: 'heater_on_at', cacheKey: 'cycles',
        emptyText: 'No heating cycles yet.', errorText: 'Unable to load heating cycles.',
        renderRows: function (items) { return items.map(renderCycleCard).join(''); }
    });

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

    var LISTS = { sessions: sessionsList, cycles: cyclesList, events: eventsList, commands: commandsList };

    // --- session detail modal ------------------------------------------------------

    function renderSessionDetailModal(session) {
        var body = el('eidli-session-modal-body');
        if (!session) { body.innerHTML = '<div class="eidli-section-error">Unable to load session detail.</div>'; return; }
        var html = '<div class="mb-2"><span class="fw-semibold fs-5">Session #' + esc(session.session_number) + '</span> ' + E.sessionStatusBadge(session.status) + '</div>';
        html += '<div class="row g-2 small mb-3">';
        html += '<div class="col-6">Started: <strong>' + esc(fmtDateTime(session.started_at)) + '</strong></div>';
        html += '<div class="col-6">Ended: <strong>' + esc(fmtDateTime(session.completed_at)) + '</strong></div>';
        html += '<div class="col-6">Duration: <strong>' + fmtDuration(session.duration_seconds) + '</strong></div>';
        html += '<div class="col-6">Heating Cycles: <strong>' + (session.heating_cycle_count != null ? session.heating_cycle_count : '—') + '</strong></div>';
        html += '<div class="col-6">Start Temperature: <strong>' + fmtTemp(session.start_temperature) + '</strong></div>';
        html += '<div class="col-6">Target Temperature: <strong>' + fmtTemp(session.target_temperature) + '</strong></div>';
        html += '<div class="col-6">Maximum Temperature: <strong>' + fmtTemp(session.max_temperature) + '</strong></div>';
        html += '</div>';
        if (session.end_reason) html += '<div class="eidli-alert eidli-alert-bad py-2 small">' + esc(session.end_reason) + '</div>';

        html += '<h6 class="mt-3">Heating Cycles in This Session</h6>';
        if (!cyclesList.isLoaded()) {
            html += '<div class="eidli-section-empty">Open the Heating Cycles tab first to cross-reference cycles for this session.</div>';
        } else {
            var cycles = cyclesList.getItems().filter(function (c) { return c.cooking_session_id === session.id; });
            html += cycles.length ? cycles.map(renderCycleCard).join('') : '<div class="eidli-section-empty">No heating cycles from the currently loaded batch belong to this session — load more on the Heating Cycles tab if this session is older.</div>';
        }
        body.innerHTML = html;
    }

    function openSessionDetail(sessionId) {
        var modalEl = el('eidli-session-modal');
        if (!modalEl || typeof bootstrap === 'undefined') return;
        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        el('eidli-session-modal-body').innerHTML = '<div class="eidli-section-loading">Loading session…</div>';
        modal.show();
        apiFetch(URLS.sessionDetailTpl.replace('__ID__', sessionId)).then(function (res) {
            if (!res.ok || !res.body.success) { el('eidli-session-modal-body').innerHTML = '<div class="eidli-section-error">' + esc(errMsg(res, 'Unable to load session detail.')) + '</div>'; return; }
            renderSessionDetailModal(res.body.data);
        }).catch(function () { el('eidli-session-modal-body').innerHTML = '<div class="eidli-section-error">Unable to load session detail.</div>'; });
    }

    // --- tabs ------------------------------------------------------------------

    function activateTab(tab) {
        var t0 = performance.now();
        currentTab = tab;
        document.querySelectorAll('#eidli-hist-tabs .nav-link').forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-tab') === tab);
        });
        document.querySelectorAll('.eidli-hist-pane').forEach(function (p) {
            p.style.display = (p.getAttribute('data-pane') === tab) ? 'block' : 'none';
        });
        // All four lists are eager-loaded on page open now (see
        // DOMContentLoaded below), so this is normally already loaded by
        // the time a tab is actually clicked — the isLoaded() check plus
        // load()'s own in-flight guard make this a safe no-op fallback
        // rather than a real fetch trigger in the common case.
        var list = LISTS[tab];
        if (list && !list.isLoaded()) list.load(true);
        console.debug('[history-timing] tab switch to', tab, 'DOM update took', (performance.now() - t0).toFixed(1), 'ms');
        // Machine Runtime Analytics is its own tab pane now, display:none
        // until selected. Its chart may have been constructed (page load
        // fetches it eagerly regardless of active tab) while still hidden,
        // in which case Chart.js sized the canvas to 0 — resize() once the
        // pane is actually visible corrects that.
        if (tab === 'runtime') {
            if (runtimeChart) runtimeChart.resize();
            startRuntimeAutoRefresh();
        } else {
            stopRuntimeAutoRefresh();
        }
    }

    function initTabs() {
        var tabButtons = document.querySelectorAll('#eidli-hist-tabs .nav-link');
        tabButtons.forEach(function (b) {
            b.addEventListener('click', function () { activateTab(b.getAttribute('data-tab')); });
        });
        var validTabs = Array.prototype.map.call(tabButtons, function (b) { return b.getAttribute('data-tab'); });
        var requested = new URLSearchParams(window.location.search).get('tab');
        activateTab((requested && validTabs.indexOf(requested) !== -1) ? requested : 'sessions');
    }

    // --- date range --------------------------------------------------------------

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
            }
            if (fromDate !== expectedFrom || toDate !== expectedTo || fromTime !== '00:00' || toTime !== '23:59') {
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
        // Sessions/Cycles/Events/Commands AND Machine Runtime Analytics —
        // so "Yesterday" applies everywhere at once, not just to whichever
        // tab happens to be on screen right now. (Previously only the
        // active tab refetched immediately and the other three waited
        // until the user actually clicked into them — that's the bug this
        // fixes.) Tabs not currently visible still update their data in
        // the background; activateTab()'s own isLoaded() check just finds
        // them already fresh whenever the user switches to one.
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

        var promises = Object.keys(LISTS).map(function (k) { return LISTS[k].load(true); });
        promises.push(fetchRuntimeAnalytics());

        Promise.all(promises).then(function (results) {
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
        highlightDatePreset(null);
        applyDateRange();
    }

    // Today/Yesterday/Last-7-Days need the IST calendar date, not whatever
    // date it happens to be in the viewer's own browser timezone — reuses
    // core.js's istDateISO() (built on the same IST_TZ constant every other
    // timestamp on this app is already formatted with) rather than a
    // second, separate timezone calculation. IST has no DST, so subtracting
    // a fixed number of 24h days from `now` and reading its IST calendar
    // date is exact — there's no daylight-saving edge case to account for.
    var ONE_DAY_MS = 24 * 60 * 60 * 1000;

    function initDateControls() {
        el('eidli-hist-apply').addEventListener('click', applyDateRange);
        el('eidli-hist-clear').addEventListener('click', clearDateRange);
        document.querySelectorAll('.eidli-date-preset').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var now = new Date();
                var p = btn.getAttribute('data-preset');
                var fromStr = E.istDateISO(now), toStr = E.istDateISO(now);
                if (p === 'yesterday') {
                    var yesterday = E.istDateISO(new Date(now.getTime() - ONE_DAY_MS));
                    fromStr = yesterday; toStr = yesterday;
                } else if (p === 'week') {
                    fromStr = E.istDateISO(new Date(now.getTime() - 6 * ONE_DAY_MS));
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
        // Runtime Analytics is now a page-level widget (not nested under the
        // Sessions tab), so any of the section Refresh buttons — the only
        // "refresh" controls this page has — also re-runs it, alongside that
        // section's own unchanged refresh behavior.
        el('eidli-sessions-refresh').addEventListener('click', function () { sessionsList.load(true); fetchRuntimeAnalytics(); });
        el('eidli-sessions-more').addEventListener('click', function () { sessionsList.load(false); });
        el('eidli-sessions-status').addEventListener('change', function () { sessionsList.render(); });
        el('eidli-cycles-refresh').addEventListener('click', function () { cyclesList.load(true); fetchRuntimeAnalytics(); });
        el('eidli-cycles-more').addEventListener('click', function () { cyclesList.load(false); });
        el('eidli-cycles-status').addEventListener('change', function () { cyclesList.render(); });
        el('eidli-events-refresh').addEventListener('click', function () { eventsList.load(true); fetchRuntimeAnalytics(); });
        el('eidli-events-more').addEventListener('click', function () { eventsList.load(false); });
        el('eidli-commands-refresh').addEventListener('click', function () { commandsList.load(true); fetchRuntimeAnalytics(); });
        el('eidli-commands-more').addEventListener('click', function () { commandsList.load(false); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        E.startHeader();
        initDateControls();
        initRefreshAndMore();
        initRuntimeAnalytics();
        if (!CONFIGURED) {
            Object.keys(LISTS).forEach(function (k) { el('eidli-' + k + '-body').innerHTML = '<div class="eidli-section-empty">Not connected.</div>'; });
            el('eidli-runtime-chart').parentNode.innerHTML = '<div class="eidli-section-empty">Not connected.</div>';
            return;
        }
        // Instant paint from whatever was cached the last time this page
        // was open in this tab — before initTabs()/activateTab() runs and
        // before any of the eager loads below have even been dispatched.
        Object.keys(LISTS).forEach(function (k) { LISTS[k].hydrate(); });
        hydrateRuntimeFromCache();

        initTabs();

        // All four lists load in parallel up front now, instead of lazily
        // per tab click — so every subsequent tab switch (Sessions <->
        // Cycles <-> Events <-> Commands) is instant: no fetch, no spinner,
        // data's already there. initTabs()'s activateTab() call above may
        // have already started loading the initial tab; load()'s own
        // in-flight guard makes sure that doesn't turn into a duplicate
        // request for the same tab.
        Object.keys(LISTS).forEach(function (k) { LISTS[k].load(true); });
        fetchRuntimeAnalytics();

        // Sessions/Cycles/Events/Commands now refresh automatically too —
        // whichever tab is actually on screen, so a session completing
        // elsewhere shows up here without a reload. Runtime Analytics has
        // its own separate, already-running auto-refresh (see
        // startRuntimeAutoRefresh) and isn't duplicated here.
        setInterval(function () {
            if (document.visibilityState !== 'visible') return;
            var list = LISTS[currentTab];
            if (list) list.load(true);
        }, HISTORY_AUTO_REFRESH_MS);
    });
})();
