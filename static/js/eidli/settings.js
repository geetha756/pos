/*
 * Electric Idli Machine — Settings page.
 *
 * Reads/writes the PATCH /settings endpoint - the backend-owned settings
 * record this page fetches fresh on every load, never a local copy of
 * truth.
 */
(function () {
    var E = window.Eidli;
    var el = E.el, esc = E.esc, apiFetch = E.apiFetch, errMsg = E.errMsg;
    var URLS = E.URLS, CONFIGURED = E.CONFIGURED;

    var lastSettings = null;
    var syncInFlight = false;

    function renderSettings(settings) {
        lastSettings = settings;
        var body = el('eidli-settings-body');
        if (!settings) { body.innerHTML = '<div class="eidli-section-empty">Settings unavailable.</div>'; return; }

        var html = '<form id="eidli-settings-form">';
        html += '<div class="row g-3">';
        html += '<div class="col-sm-6 col-lg-3"><label class="form-label">Off Threshold (°C)</label>' +
            '<input type="number" step="0.01" min="0" max="100" class="form-control" id="eidli-set-off" value="' + esc(settings.off_temperature) + '">' +
            '<div class="form-text">Heater turns off when this is reached.</div></div>';
        html += '<div class="col-sm-6 col-lg-3"><label class="form-label">Restart Threshold (°C)</label>' +
            '<input type="number" step="0.01" min="0" max="100" class="form-control" id="eidli-set-on" value="' + esc(settings.on_temperature) + '">' +
            '<div class="form-text">Heater restarts once temperature drops to this.</div></div>';
        html += '<div class="col-sm-6 col-lg-3"><label class="form-label">Temperature Offset (°C)</label>' +
            '<input type="number" step="0.01" min="-10" max="10" class="form-control" id="eidli-set-offset" value="' + esc(settings.temperature_offset) + '">' +
            '<div class="form-text">Sensor calibration correction.</div></div>';
        html += '<div class="col-sm-6 col-lg-3"><label class="form-label d-block">Buzzer Alerts</label>' +
            '<div class="eidli-switch-field">' +
            '<div class="form-check form-switch mb-0">' +
            '<input class="form-check-input" type="checkbox" id="eidli-set-buzzer"' + (settings.buzzer_enabled ? ' checked' : '') + '>' +
            '<label class="form-check-label" for="eidli-set-buzzer">Enabled</label></div>' +
            '</div>' +
            '<div class="form-text">Audible alerts from the machine.</div></div>';
        html += '</div>';
        html += '<div class="d-flex gap-2 mt-3">';
        html += '<button type="submit" class="btn btn-success">Save Settings</button>';
        html += '</div>';
        html += '<div id="eidli-settings-msg" class="mt-2 small"></div>';
        html += '</form>';
        body.innerHTML = html;

        el('eidli-settings-form').addEventListener('submit', onSaveSettings);
        updateSyncButton();
    }

    function onSaveSettings(e) {
        e.preventDefault();
        var msg = el('eidli-settings-msg');
        var body = {};
        var off = el('eidli-set-off').value, on = el('eidli-set-on').value, offset = el('eidli-set-offset').value;

        // Blocks the save entirely — no API call — the instant either
        // threshold exceeds 100°C, with the exact message text this needs,
        // rather than relying on the native max="100" bubble or waiting on
        // a round-trip to the backend's own validation to find out.
        var offNum = parseFloat(off);
        if (!isNaN(offNum) && offNum > 100) {
            msg.textContent = 'Off Threshold must be less than or equal to 100°C.'; msg.className = 'mt-2 small text-danger';
            return;
        }
        var onNum = parseFloat(on);
        if (!isNaN(onNum) && onNum > 100) {
            msg.textContent = 'Restart Threshold must be less than or equal to 100°C.'; msg.className = 'mt-2 small text-danger';
            return;
        }

        if (!lastSettings || off !== String(lastSettings.off_temperature)) body.off_temperature = off;
        if (!lastSettings || on !== String(lastSettings.on_temperature)) body.on_temperature = on;
        if (!lastSettings || offset !== String(lastSettings.temperature_offset)) body.temperature_offset = offset;

        var buzzer = el('eidli-set-buzzer').checked;
        if (!lastSettings || buzzer !== lastSettings.buzzer_enabled) body.buzzer_enabled = buzzer;

        if (!Object.keys(body).length) { msg.textContent = 'No changes to save.'; msg.className = 'mt-2 small text-muted'; return; }
        if (!confirm('Save these machine settings?\n\nThis changes real heater thresholds on the machine.')) return;

        var submitBtn = el('eidli-settings-form').querySelector('button[type=submit]');
        submitBtn.disabled = true;
        msg.textContent = 'Saving…'; msg.className = 'mt-2 small text-warning';
        apiFetch(URLS.settings, { method: 'PATCH', body: JSON.stringify(body) }).then(function (res) {
            submitBtn.disabled = false;
            if (res.ok && res.body.success) {
                msg.textContent = 'Saved.'; msg.className = 'mt-2 small text-success';
                window.showToast('success', 'Settings saved.');
                renderSettings(res.body.data);
            } else {
                var m = errMsg(res, 'Failed to save settings.');
                msg.textContent = m; msg.className = 'mt-2 small text-danger';
                window.showToast('danger', 'Settings save failed: ' + m);
            }
        }).catch(function () {
            submitBtn.disabled = false;
            msg.textContent = 'Network error.'; msg.className = 'mt-2 small text-danger';
        });
    }

    function refreshSettings() {
        if (!CONFIGURED) return;
        apiFetch(URLS.settings).then(function (res) {
            if (!res.ok || !res.body.success) { el('eidli-settings-body').innerHTML = '<div class="eidli-section-error">Unable to load settings.</div>'; return; }
            renderSettings(res.body.data);
        }).catch(function () { el('eidli-settings-body').innerHTML = '<div class="eidli-section-error">Unable to load settings.</div>'; });
    }

    // --- sync command (heavier-weight config push, its own ack flow) -------------

    function updateSyncButton() {
        var btn = el('eidli-settings-sync-btn');
        var status = E.getLastStatus();
        btn.disabled = !CONFIGURED || !(status && status.is_online) || syncInFlight;
    }

    function setSyncStatus(text, cls) {
        var e = el('eidli-sync-status');
        e.textContent = text; e.className = 'eidli-cmd-status ' + (cls || '');
    }

    function pollSyncAck(requestId) {
        if (!requestId) { syncInFlight = false; updateSyncButton(); setSyncStatus('Sent — command accepted.', 'state-success'); return; }
        var attempts = 0, maxAttempts = 8;
        var iv = setInterval(function () {
            attempts++;
            apiFetch(URLS.commands + '?limit=20').then(function (res) {
                if (res.ok && res.body.success) {
                    var items = (res.body.data && res.body.data.items) || [];
                    var match = null;
                    for (var i = 0; i < items.length; i++) { if (items[i].request_id === requestId) { match = items[i]; break; } }
                    if (match && match.status !== 'pending') {
                        clearInterval(iv); syncInFlight = false; updateSyncButton();
                        if (match.status === 'success') { setSyncStatus('Settings synced to the machine ✓', 'state-success'); window.showToast('success', 'Settings synced.'); }
                        else if (match.status === 'timeout') { setSyncStatus('Sync timed out ⚠', 'state-failed'); window.showToast('danger', 'Settings sync timed out.'); }
                        else { setSyncStatus(match.response_message || 'Sync failed.', 'state-failed'); window.showToast('danger', 'Settings sync failed.'); }
                        return;
                    }
                }
                if (attempts >= maxAttempts) { clearInterval(iv); syncInFlight = false; updateSyncButton(); setSyncStatus('Still pending — check History → Commands.', 'state-pending'); }
            }).catch(function () {
                if (attempts >= maxAttempts) { clearInterval(iv); syncInFlight = false; updateSyncButton(); setSyncStatus('Sent — could not confirm the outcome yet.', 'state-pending'); }
            });
        }, 2000);
    }

    function dispatchSync() {
        if (syncInFlight) return;
        if (!confirm('Push the current saved settings down to the machine now?')) return;
        syncInFlight = true; updateSyncButton();
        setSyncStatus('Sending…', 'state-pending');
        apiFetch(URLS.settingsSync, { method: 'POST' }).then(function (res) {
            if (!res.ok || !res.body.success) {
                syncInFlight = false; updateSyncButton();
                setSyncStatus('Failed — ' + errMsg(res, 'unknown error'), 'state-failed');
                return;
            }
            setSyncStatus('Published — waiting for the machine to acknowledge…', 'state-pending');
            pollSyncAck((res.body.data || {}).request_id);
        }).catch(function () {
            syncInFlight = false; updateSyncButton();
            setSyncStatus('Failed — could not reach the server.', 'state-failed');
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        E.startHeader();
        if (!CONFIGURED) { el('eidli-settings-body').innerHTML = '<div class="eidli-section-empty">Not connected.</div>'; return; }
        el('eidli-settings-sync-btn').addEventListener('click', dispatchSync);
        E.onStatus(updateSyncButton);
        refreshSettings();
    });
})();
