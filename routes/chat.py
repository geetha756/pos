"""
BitBerry chat agent integration.

BitBerry is the single source of truth for which agents a user can talk to
— this app never stores its own user-to-agent mapping. On login (and
whenever the dashboard loads), we ask BitBerry which agents are assigned to
the signed-in user (by their Google identity) and surface those as cards/
notifications. The browser never talks to BitBerry directly (it would need
the user's Google ID token, which we deliberately keep server-side only);
every call is proxied through this module.
"""
from flask import Blueprint, render_template, request, session, jsonify, Response, stream_with_context, current_app
from .auth import login_required
from security import permission_required
import os
import time
import requests as req

chat_bp = Blueprint('chat', __name__)

BITBERRY_BASE_URL = os.getenv('BITBERRY_BASE_URL', 'https://test-bitberry.snfifteen.com')
BITBERRY_CHAT_URL = os.getenv('BITBERRY_API_URL', BITBERRY_BASE_URL.rstrip('/') + '/api/chat/completions')
BITBERRY_AGENTS_URL = os.getenv('BITBERRY_AGENTS_URL', BITBERRY_BASE_URL.rstrip('/') + '/api/v1/users/me/agents')

# BitBerry is an external service on the open internet; a hung connection
# must not tie up a worker forever. (connect timeout, read timeout) — read
# is generous on the chat call since agent responses (especially with tool
# calls) can be slow; the agents-list call is small and gets a tighter one.
_CHAT_TIMEOUT = (10, 90)
_AGENTS_TIMEOUT = (10, 30)

# How long a fetched agent list stays valid in the session before we ask
# BitBerry again. Session-scoped only (per "cache for the current session,
# refresh on next login") — not a shared/global cache across users.
_AGENTS_CACHE_TTL_SECONDS = 300


def _google_token_status():
    """('ok'|'missing'|'expired', token_or_None)."""
    token = session.get('google_id_token')
    if not token:
        return 'missing', None
    exp = session.get('google_id_token_exp')
    # A small safety margin: don't hand BitBerry a token that expires mid-request.
    if exp and float(exp) <= (time.time() + 30):
        return 'expired', None
    return 'ok', token


def _fetch_agents_from_bitberry(token):
    """Call BitBerry's assigned-agents endpoint. Returns (agents_list, error_dict).
    Exactly one of the two is populated. error_dict has 'status' (HTTP code
    to return to the browser) and 'error'/'message' matching the same error
    vocabulary as the chat endpoint."""
    try:
        resp = req.get(
            BITBERRY_AGENTS_URL,
            headers={'Authorization': f'Bearer {token}'},
            timeout=_AGENTS_TIMEOUT,
        )
    except req.exceptions.Timeout:
        return None, {'status': 504, 'error': 'timeout', 'message': 'BitBerry took too long to respond.'}
    except req.exceptions.RequestException as e:
        return None, {'status': 502, 'error': 'network_error', 'message': str(e)}

    if resp.status_code == 401:
        return None, {'status': 401, 'error': 'invalid_token', 'message': 'Invalid or expired token.'}
    if resp.status_code == 404:
        return None, {'status': 404, 'error': 'agent_unavailable', 'message': 'Agent unavailable or access denied.'}
    if resp.status_code >= 500:
        return None, {'status': 502, 'error': 'backend_failure', 'message': 'The BitBerry backend failed to respond.'}
    if resp.status_code >= 400:
        return None, {'status': 502, 'error': 'upstream_error', 'message': f'BitBerry returned HTTP {resp.status_code}.'}

    try:
        data = resp.json()
    except ValueError:
        return None, {'status': 502, 'error': 'backend_failure', 'message': 'BitBerry returned a non-JSON response.'}

    return (data.get('agents') or []), None


def get_assigned_agents(force_refresh=False):
    """Session-cached list of agents assigned to the current user. Returns
    (agents_list, error_dict) — same contract as _fetch_agents_from_bitberry.
    A None agents_list with error_dict=None means "not logged in / no token",
    which callers should treat as an empty list rather than an error banner
    (chat.view-gated pages already require login, so this mainly guards
    against a token that hasn't refreshed yet)."""
    status, token = _google_token_status()
    if status != 'ok':
        return [], {'status': 401, 'error': 'reauth_required', 'message': 'Your session needs to be refreshed.'}

    cached = session.get('bitberry_agents_cache')
    if not force_refresh and cached and cached.get('fetched_at', 0) > time.time() - _AGENTS_CACHE_TTL_SECONDS:
        return cached['agents'], None

    agents, error = _fetch_agents_from_bitberry(token)
    if error:
        # Serve stale cache on a transient failure rather than blanking out
        # previously-known agents just because BitBerry hiccupped once.
        if cached:
            return cached['agents'], None
        return [], error

    session['bitberry_agents_cache'] = {'agents': agents, 'fetched_at': time.time()}
    return agents, None


@chat_bp.route('/api/agents', methods=['GET'])
@login_required
@permission_required('chat.view')
def api_agents():
    """Agents assigned to the current user, per BitBerry. Called on dashboard
    load and whenever the chat page needs to resolve/validate an agent id."""
    force_refresh = request.args.get('refresh') == '1'
    agents, error = get_assigned_agents(force_refresh=force_refresh)
    if error:
        return jsonify({'error': error['error'], 'message': error['message']}), error['status']
    return jsonify({'agents': agents})


@chat_bp.route('/')
@login_required
@permission_required('chat.view')
def dashboard():
    """Chat page. ?agent=<id> selects which assigned agent this conversation
    talks to; the client resolves/validates it against /api/agents on load
    (a bookmarked/stale agent id that's no longer assigned just shows a
    'pick another agent' state instead of silently calling BitBerry with it)."""
    return render_template('chat/dashboard.html', requested_agent_id=request.args.get('agent', ''))


@chat_bp.route('/api/send', methods=['POST'])
@login_required
@permission_required('chat.view')
def api_send():
    """Forward the full conversation to BitBerry and return its reply.

    Body: {"agent": "<agent_id>", "messages": [{"role": ..., "content": ...}, ...], "stream": bool}
    The caller is expected to resend the entire history each time (BitBerry
    is stateless per-request) — we don't persist conversations server-side.
    """
    payload = request.get_json(silent=True) or {}
    agent_id = (payload.get('agent') or '').strip()
    messages = payload.get('messages')

    if not agent_id:
        return jsonify({'error': 'bad_request', 'message': 'agent is required.'}), 400
    if not isinstance(messages, list) or not messages:
        return jsonify({'error': 'bad_request', 'message': 'messages must be a non-empty list.'}), 400

    status, token = _google_token_status()
    if status != 'ok':
        # 401 here means "you (the browser) need to sign in again", distinct
        # from a 401 BitBerry itself might return for a token it rejects.
        return jsonify({'error': 'reauth_required', 'message': 'Your session needs to be refreshed.'}), 401

    stream = bool(payload.get('stream'))
    upstream_body = {'model': agent_id, 'messages': messages}
    if stream:
        upstream_body['stream'] = True

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    }

    try:
        upstream = req.post(
            BITBERRY_CHAT_URL,
            json=upstream_body,
            headers=headers,
            timeout=_CHAT_TIMEOUT,
            stream=stream,
        )
    except req.exceptions.Timeout:
        return jsonify({'error': 'timeout', 'message': 'The BitBerry agent took too long to respond.'}), 504
    except req.exceptions.RequestException as e:
        return jsonify({'error': 'network_error', 'message': str(e)}), 502

    if upstream.status_code == 401:
        return jsonify({'error': 'invalid_token', 'message': 'Invalid or expired token.'}), 401
    if upstream.status_code == 404:
        return jsonify({'error': 'agent_unavailable', 'message': 'Agent unavailable or access denied.'}), 404
    if upstream.status_code >= 500:
        return jsonify({'error': 'backend_failure', 'message': 'The BitBerry backend failed to respond.'}), 502
    if upstream.status_code >= 400:
        return jsonify({'error': 'upstream_error', 'message': f'BitBerry returned HTTP {upstream.status_code}.'}), 502

    if not stream:
        try:
            data = upstream.json()
        except ValueError:
            return jsonify({'error': 'backend_failure', 'message': 'BitBerry returned a non-JSON response.'}), 502
        content = (
            data.get('choices', [{}])[0]
                .get('message', {})
                .get('content', '')
        )
        return jsonify({'content': content})

    # Streaming: relay BitBerry's SSE-style chunks to the browser as they
    # arrive, so the reply renders incrementally instead of waiting for the
    # whole response.
    def relay():
        try:
            for line in upstream.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                yield line + '\n'
        except req.exceptions.RequestException:
            yield 'data: {"error": "network_error"}\n\n'
        finally:
            upstream.close()

    return Response(
        stream_with_context(relay()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@chat_bp.route('/api/reauth-check', methods=['GET'])
@login_required
def api_reauth_check():
    """Lightweight status check the chat UI can poll after bouncing through
    silent reauth, to confirm the session now has a usable token."""
    status, _ = _google_token_status()
    return jsonify({'status': status})
