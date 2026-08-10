"""
Centralized client for the Electric Idli Machine FastAPI backend
(ESP32 -> MQTT -> FastAPI -> this client -> POS). Every call the POS makes
to that service goes through here so routes/machines.py doesn't scatter
raw `requests` calls, and so a backend contract change only needs to be
handled in one place.

Contract source: the real OpenAPI 3.1 spec (service "Idli Machine Backend"
v0.1.0) supplied for this integration — not guessed. Where this module
makes an inference beyond what was explicitly documented (marked NOTE
below), it's because the contract didn't specify that detail; these are
the few remaining gaps to confirm with the backend team.
"""
import os
import requests

BASE_URL = os.getenv('EIDLI_API_BASE_URL', '').rstrip('/')
API_KEY = os.getenv('EIDLI_API_KEY', '').strip()
REQUEST_TIMEOUT = 5  # seconds — a hung backend call must not hang the page


class EidliError(Exception):
    """Any failure talking to the machine backend. `status` is the HTTP
    status this should surface to the browser as."""
    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status


class EidliConflict(EidliError):
    """409 from the backend — e.g. a cooking session is already active.
    The backend is the final concurrency authority; the frontend just
    surfaces this rather than pre-guessing it."""
    def __init__(self, message):
        super().__init__(message, 409)


def configured():
    return bool(BASE_URL)


def _headers():
    # The backend requires X-API-Key on its mutating endpoints (POST/PATCH
    # commands, settings writes, session lifecycle); GETs are unauthenticated.
    # Confirmed against the live OpenAPI contract and a direct 401 test.
    headers = {}
    if API_KEY:
        headers['X-API-Key'] = API_KEY
    return headers


def _safe_message(resp):
    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    # Confirmed live: this backend's error envelope is
    # {"error": {"type": "...", "message": "..."}}, not FastAPI's default
    # {"detail": "..."} — checked first. The detail/message fallbacks stay
    # as a safety net in case other error paths use a different shape.
    err = data.get('error')
    if isinstance(err, dict) and err.get('message'):
        return err['message']
    return data.get('detail') or data.get('message')


def _request(method, path, **kwargs):
    if not BASE_URL:
        raise EidliError('Electric Idli Machine integration is not configured.', 503)

    url = f'{BASE_URL}{path}'
    try:
        resp = requests.request(method, url, headers=_headers(), timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.exceptions.Timeout:
        raise EidliError('The machine service did not respond in time.', 504)
    except requests.exceptions.RequestException:
        raise EidliError('Could not reach the machine service.', 502)

    if resp.status_code == 404:
        raise EidliError(_safe_message(resp) or 'Not found.', 404)
    if resp.status_code == 409:
        raise EidliConflict(_safe_message(resp) or 'Conflict.')
    if resp.status_code >= 400:
        status = 502 if resp.status_code >= 500 else resp.status_code
        raise EidliError(_safe_message(resp) or f'Machine service returned {resp.status_code}.', status)

    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        raise EidliError('Machine service returned an unexpected response.', 502)


def _paged_params(limit=None, offset=None, extra=None):
    # NOTE: the contract confirms the *response* shape includes limit/offset
    # (items/total/limit/offset), which strongly implies these are also the
    # accepted request query params (the response echoes them back) — but
    # this isn't spelled out explicitly for the request side. Flagged as a
    # detail worth a one-line confirmation from the backend team.
    params = dict(extra or {})
    if limit is not None:
        params['limit'] = limit
    if offset is not None:
        params['offset'] = offset
    return params


# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------

def get_machine(machine_id):
    return _request('GET', f'/api/v1/machines/{machine_id}')


def get_machine_status(machine_id):
    """Lightweight status — the endpoint the contract recommends for
    frequent polling."""
    return _request('GET', f'/api/v1/machines/{machine_id}/status')


# ---------------------------------------------------------------------------
# Background /status poller
# ---------------------------------------------------------------------------
# Measured directly against the live backend: /status takes 400ms-1000ms
# and varies a lot call to call, while every other endpoint here
# (/sessions/current, /heating-cycles, /events, /sessions/today,
# /temperature-logs) is consistently under 300ms. That latency + variance
# signature points at a live device round-trip (ESP32/MQTT) rather than a
# database read — something on the separate backend service, not something
# this client can fix directly (out of scope to modify that service).
#
# What IS in scope: not making the browser wait on it. A daemon thread
# polls /status on its own schedule and keeps the latest result in memory;
# routes/machines.py's /idli/api/status route reads straight from here
# instead of blocking on a fresh call per request, so the Dashboard's
# status/temperature/heater/machine/sensor section renders in the time it
# takes to read a Python variable, not the time it takes the machine
# service to round-trip to the physical device.
import threading
import time

_status_cache_lock = threading.Lock()
_status_cache = {'data': None, 'error': None}
_status_poller_started = False
STATUS_POLL_INTERVAL = 2.0  # seconds — matches the frontend's own poll cadence


def _status_poller_loop(machine_id):
    while True:
        try:
            data = get_machine_status(machine_id)
            with _status_cache_lock:
                _status_cache['data'] = data
                _status_cache['error'] = None
        except EidliError as e:
            with _status_cache_lock:
                _status_cache['error'] = e
        except Exception:
            pass  # never let a transient failure kill the poller thread
        time.sleep(STATUS_POLL_INTERVAL)


def start_status_poller(machine_id):
    """Idempotent — safe to call more than once (only the first call
    actually starts the thread). No-ops if unconfigured or no machine id,
    same as every other function here would."""
    global _status_poller_started
    if _status_poller_started or not machine_id or not configured():
        return
    _status_poller_started = True
    t = threading.Thread(target=_status_poller_loop, args=(machine_id,), daemon=True)
    t.start()


def get_cached_status():
    """The poller's latest /status result, returned instantly (no network
    call). Returns None if the poller hasn't produced a result yet (e.g.
    the first request or two right after the server starts) or was never
    started — callers should fall back to a direct get_machine_status()
    call in that case, same as before this existed."""
    with _status_cache_lock:
        if _status_cache['data'] is not None:
            return _status_cache['data']
        error = _status_cache['error']
    if error is not None:
        raise error
    return None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_settings(machine_id):
    return _request('GET', f'/api/v1/machines/{machine_id}/settings')


def update_settings(machine_id, fields):
    """Partial update via PATCH — only send fields actually being changed,
    per the contract."""
    return _request('PATCH', f'/api/v1/machines/{machine_id}/settings', json=fields)


# ---------------------------------------------------------------------------
# Temperature history
# ---------------------------------------------------------------------------

def get_temperature_logs(machine_id, limit=None, offset=None, start_time=None, end_time=None):
    params = _paged_params(limit, offset, {'start_time': start_time, 'end_time': end_time})
    return _request('GET', f'/api/v1/machines/{machine_id}/temperature-logs', params=params)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def get_events(machine_id, limit=None, offset=None, start_time=None, end_time=None):
    params = _paged_params(limit, offset, {'start_time': start_time, 'end_time': end_time})
    return _request('GET', f'/api/v1/machines/{machine_id}/events', params=params)


# ---------------------------------------------------------------------------
# Remote commands
# ---------------------------------------------------------------------------

def heater_on(machine_id):
    return _request('POST', f'/api/v1/machines/{machine_id}/heater/on')


def heater_off(machine_id):
    return _request('POST', f'/api/v1/machines/{machine_id}/heater/off')


def restart_machine(machine_id):
    return _request('POST', f'/api/v1/machines/{machine_id}/restart')


def sync_settings(machine_id):
    return _request('POST', f'/api/v1/machines/{machine_id}/settings/sync')


def get_commands(machine_id, limit=None, offset=None, start_time=None, end_time=None):
    params = _paged_params(limit, offset, {'start_time': start_time, 'end_time': end_time})
    return _request('GET', f'/api/v1/machines/{machine_id}/commands', params=params)


# ---------------------------------------------------------------------------
# Cooking sessions
# ---------------------------------------------------------------------------

def start_session(machine_id):
    return _request('POST', f'/api/v1/machines/{machine_id}/sessions/start')


def complete_session(machine_id, session_id, reason=None):
    kwargs = {'json': {'reason': reason}} if reason else {}
    return _request('POST', f'/api/v1/machines/{machine_id}/sessions/{session_id}/complete', **kwargs)


def get_current_session(machine_id):
    """Returns None when there is no active session.

    NOTE: the contract doesn't specify exactly what "current" returns when
    nothing is active (404 vs. a null 200 body). We treat a 404 here as
    "no active session" rather than an error, and also treat a null/empty
    200 body as "no active session" — the most standard REST reading of a
    singleton /current resource, but not explicitly confirmed."""
    try:
        return _request('GET', f'/api/v1/machines/{machine_id}/sessions/current')
    except EidliError as e:
        if e.status == 404:
            return None
        raise


def get_session(machine_id, session_id):
    return _request('GET', f'/api/v1/machines/{machine_id}/sessions/{session_id}')


def get_sessions(machine_id, limit=None, offset=None, start_time=None, end_time=None):
    params = _paged_params(limit, offset, {'start_time': start_time, 'end_time': end_time})
    return _request('GET', f'/api/v1/machines/{machine_id}/sessions', params=params)


def get_daily_session_summary(machine_id):
    """Today's session summary for the dashboard (sessions completed today,
    lifetime total, today's session rank) — GET /sessions/today. Added once
    the confirmed contract exposed this; previously the dashboard could only
    show a lifetime total (via GET /sessions' `total`), not a real
    today-only count, since no date-filtered endpoint existed yet."""
    return _request('GET', f'/api/v1/machines/{machine_id}/sessions/today')


# ---------------------------------------------------------------------------
# Heating cycles
# ---------------------------------------------------------------------------

def get_heating_cycles(machine_id, limit=None, offset=None, start_time=None, end_time=None):
    params = _paged_params(limit, offset, {'start_time': start_time, 'end_time': end_time})
    return _request('GET', f'/api/v1/machines/{machine_id}/heating-cycles', params=params)
