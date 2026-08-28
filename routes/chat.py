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
import uuid
import logging
import requests as req

chat_bp = Blueprint('chat', __name__)

# Two separate loggers for /api/send (see api_send), so each can be tuned
# independently of general app log noise and of each other:
#   pos.chat.timing      — latency milestones (see the class docstring there)
#   pos.chat.diagnostics — WHERE a failed/empty reply actually broke: a
#                          BitBerry-side error/empty response vs a proxy/
#                          relay-side bug in this app, vs a network problem
#                          reaching BitBerry at all. This is the log to check
#                          when "the agent didn't respond" — it tells you
#                          which side of the fence to keep debugging on.
# Enable with logging.getLogger('pos.chat.<name>').setLevel(logging.INFO).
_timing_log = logging.getLogger('pos.chat.timing')
_diag_log = logging.getLogger('pos.chat.diagnostics')

BITBERRY_BASE_URL = os.getenv('BITBERRY_BASE_URL', 'https://test-bitberry.snfifteen.com')
BITBERRY_CHAT_URL = os.getenv('BITBERRY_API_URL', BITBERRY_BASE_URL.rstrip('/') + '/api/chat/completions')
BITBERRY_AGENTS_URL = os.getenv('BITBERRY_AGENTS_URL', BITBERRY_BASE_URL.rstrip('/') + '/api/v1/users/me/agents')
BITBERRY_FILES_URL = os.getenv('BITBERRY_FILES_URL', BITBERRY_BASE_URL.rstrip('/') + '/api/v1/files/')

# BitBerry is an external service on the open internet; a hung connection
# must not tie up a worker forever. (connect timeout, read timeout) — read
# is generous on the chat call since agent responses (especially with tool
# calls) can be slow; the agents-list call is small and gets a tighter one.
_CHAT_TIMEOUT = (10, 90)
_AGENTS_TIMEOUT = (10, 30)
_UPLOAD_TIMEOUT = (10, 60)

# BitBerry's own instance has RAG_FILE_MAX_SIZE unset (no server-side cap) —
# per BitBerry's own recommendation, the POS imposes its own limit instead
# of relying on that. 15MB comfortably covers a phone photo of a bill.
_MAX_UPLOAD_BYTES = 15 * 1024 * 1024

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


@chat_bp.route('/api/upload', methods=['POST'])
@login_required
@permission_required('chat.view')
def api_upload():
    """Upload a file to BitBerry ahead of sending a message that references
    it. Two-step flow (BitBerry has no inline/base64 or presigned option):
    this uploads the file and returns BitBerry's file id; the client then
    includes that id in the 'files' array on the next /api/send call.
    """
    status, token = _google_token_status()
    if status != 'ok':
        return jsonify({'error': 'reauth_required', 'message': 'Your session needs to be refreshed.'}), 401

    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'error': 'bad_request', 'message': 'No file provided.'}), 400

    # Read once so we can both size-check and forward the same bytes — the
    # underlying stream can't be measured then re-read otherwise.
    file_bytes = upload.read()
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        return jsonify({
            'error': 'file_too_large',
            'message': f'File exceeds the {_MAX_UPLOAD_BYTES // (1024*1024)}MB limit.',
        }), 400
    if not file_bytes:
        return jsonify({'error': 'bad_request', 'message': 'The selected file is empty.'}), 400

    try:
        upstream = req.post(
            BITBERRY_FILES_URL,
            files={'file': (upload.filename, file_bytes, upload.mimetype or 'application/octet-stream')},
            headers={'Authorization': f'Bearer {token}'},
            timeout=_UPLOAD_TIMEOUT,
        )
    except req.exceptions.Timeout:
        return jsonify({'error': 'timeout', 'message': 'The upload took too long. Please try again.'}), 504
    except req.exceptions.RequestException as e:
        return jsonify({'error': 'network_error', 'message': str(e)}), 502

    if upstream.status_code == 401:
        return jsonify({'error': 'invalid_token', 'message': 'Invalid or expired token.'}), 401
    if upstream.status_code == 404:
        return jsonify({'error': 'agent_unavailable', 'message': 'Upload endpoint unavailable or access denied.'}), 404
    if upstream.status_code >= 500:
        return jsonify({'error': 'backend_failure', 'message': 'The BitBerry backend failed to respond.'}), 502
    if upstream.status_code >= 400:
        return jsonify({'error': 'upstream_error', 'message': f'BitBerry returned HTTP {upstream.status_code}.'}), 502

    try:
        data = upstream.json()
    except ValueError:
        return jsonify({'error': 'backend_failure', 'message': 'BitBerry returned a non-JSON response.'}), 502

    file_id = data.get('id')
    if not file_id:
        return jsonify({'error': 'backend_failure', 'message': 'BitBerry did not return a file id.'}), 502

    # BitBerry's own upload response nests the MIME type under meta; the
    # chat-completions 'files' entry needs it at content_type, so surface it
    # here rather than making the client dig through BitBerry's response
    # shape itself. Falls back to what we sent if BitBerry omits it.
    content_type = ((data.get('meta') or {}).get('content_type')) or upload.mimetype or 'application/octet-stream'

    return jsonify({
        'id': file_id,
        'filename': upload.filename,
        'content_type': content_type,
    })


def _build_bitberry_file_refs(raw_files):
    """Build the exact file-reference shape BitBerry's /api/chat/completions
    expects, from the minimal {id, filename, content_type} the client got
    back from /api/upload. Keeping this server-side (rather than trusting
    the client to assemble BitBerry's shape) means the contract lives in
    one place. Per BitBerry: 'url' is the same id (not a real URL), and
    'status' is always the literal string 'uploaded' at this point — the
    file has already finished uploading by the time it's referenced here.
    """
    refs = []
    for f in raw_files:
        if not isinstance(f, dict) or not f.get('id'):
            continue
        refs.append({
            'type': 'file',
            'id': f['id'],
            'url': f['id'],
            'name': f.get('filename') or 'file',
            'status': 'uploaded',
            'content_type': f.get('content_type') or 'application/octet-stream',
        })
    return refs


def _safe_body_preview(resp, limit=300):
    """First `limit` chars of an upstream error body, for diagnostics logs
    only — never returned to the browser. Best-effort: BitBerry error bodies
    are usually small JSON, but this must never itself raise or block on a
    large/streamed body."""
    try:
        return (resp.text or '')[:limit]
    except Exception:
        return '<unreadable>'


@chat_bp.route('/api/send', methods=['POST'])
@login_required
@permission_required('chat.view')
def api_send():
    """Forward the full conversation to BitBerry and return its reply.

    Body: {"agent": "<agent_id>", "messages": [{"role": ..., "content": ...}, ...],
           "files": [{"id": "<file-id>", "filename": "...", "content_type": "..."}, ...],
           "stream": bool}
    The caller is expected to resend the entire history each time (BitBerry
    is stateless per-request) — we don't persist conversations server-side.
    'files' applies only to the message being sent in this call (matching
    BitBerry's own chat-completions contract — it's a top-level array on
    the request, not attached to a specific message in history). Each entry
    here is the minimal shape /api/upload returns; this route expands it
    into BitBerry's full required shape (see _build_bitberry_file_refs).
    We never send tool_ids — the agent's own meta.toolIds already grants
    bill_ocr and BitBerry clamps to that allowlist regardless.

    Timing: logged to the 'pos.chat.timing' logger at each milestone this
    proxy can actually observe — request received, agent/messages
    validated, upstream request built + sent, upstream headers back (first
    byte), and (for streaming) time-to-first-chunk plus total relay time.
    Model queueing, prompt construction, and tool execution happen inside
    BitBerry itself and aren't visible from here; BitBerry would need to
    report/emit those itself for this proxy to log them.
    """
    t0 = time.perf_counter()
    # Short id so every log line for this one request can be grepped
    # together (`grep rid=<id>`), including across the timing and
    # diagnostics loggers.
    rid = uuid.uuid4().hex[:8]

    def elapsed_ms():
        return round((time.perf_counter() - t0) * 1000)

    payload = request.get_json(silent=True) or {}
    agent_id = (payload.get('agent') or '').strip()
    messages = payload.get('messages')
    raw_files = payload.get('files')

    if not agent_id:
        return jsonify({'error': 'bad_request', 'message': 'agent is required.'}), 400
    if not isinstance(messages, list) or not messages:
        return jsonify({'error': 'bad_request', 'message': 'messages must be a non-empty list.'}), 400
    if raw_files is not None and not isinstance(raw_files, list):
        return jsonify({'error': 'bad_request', 'message': 'files must be a list.'}), 400

    _timing_log.info('rid=%s request_received agent=%s stream=%s messages=%d elapsed_ms=%d',
                      rid, agent_id, bool(payload.get('stream')), len(messages), elapsed_ms())

    status, token = _google_token_status()
    if status != 'ok':
        # 401 here means "you (the browser) need to sign in again", distinct
        # from a 401 BitBerry itself might return for a token it rejects.
        _diag_log.info('rid=%s side=pos_proxy reason=no_valid_google_token agent=%s', rid, agent_id)
        return jsonify({'error': 'reauth_required', 'message': 'Your session needs to be refreshed.'}), 401

    stream = bool(payload.get('stream'))
    upstream_body = {'model': agent_id, 'messages': messages}
    if raw_files:
        file_refs = _build_bitberry_file_refs(raw_files)
        if file_refs:
            upstream_body['files'] = file_refs
    if stream:
        upstream_body['stream'] = True

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    }

    _timing_log.info('rid=%s upstream_request_built agent=%s elapsed_ms=%d', rid, agent_id, elapsed_ms())

    try:
        upstream = req.post(
            BITBERRY_CHAT_URL,
            json=upstream_body,
            headers=headers,
            timeout=_CHAT_TIMEOUT,
            stream=stream,
        )
    except req.exceptions.Timeout:
        _timing_log.warning('rid=%s upstream_timeout agent=%s elapsed_ms=%d', rid, agent_id, elapsed_ms())
        _diag_log.warning('rid=%s side=bitberry reason=timeout agent=%s elapsed_ms=%d url=%s',
                           rid, agent_id, elapsed_ms(), BITBERRY_CHAT_URL)
        return jsonify({'error': 'timeout', 'message': 'The BitBerry agent took too long to respond.'}), 504
    except req.exceptions.RequestException as e:
        _timing_log.warning('rid=%s upstream_network_error agent=%s elapsed_ms=%d', rid, agent_id, elapsed_ms())
        _diag_log.warning('rid=%s side=network reason=%s agent=%s error=%s',
                           rid, type(e).__name__, agent_id, e)
        return jsonify({'error': 'network_error', 'message': str(e)}), 502

    # requests has already read the response headers (first byte) by the
    # time .post() returns, even with stream=True — this is genuinely
    # "upstream responded", not "upstream finished".
    _timing_log.info('rid=%s upstream_headers_received agent=%s status=%d elapsed_ms=%d',
                      rid, agent_id, upstream.status_code, elapsed_ms())

    if upstream.status_code == 401:
        _diag_log.warning('rid=%s side=bitberry reason=rejected_token agent=%s', rid, agent_id)
        return jsonify({'error': 'invalid_token', 'message': 'Invalid or expired token.'}), 401
    if upstream.status_code == 404:
        _diag_log.warning('rid=%s side=bitberry reason=agent_not_found agent=%s', rid, agent_id)
        return jsonify({'error': 'agent_unavailable', 'message': 'Agent unavailable or access denied.'}), 404
    if upstream.status_code >= 500:
        _diag_log.error('rid=%s side=bitberry reason=5xx status=%d agent=%s body=%s',
                         rid, upstream.status_code, agent_id, _safe_body_preview(upstream))
        return jsonify({'error': 'backend_failure', 'message': 'The BitBerry backend failed to respond.'}), 502
    if upstream.status_code >= 400:
        _diag_log.error('rid=%s side=bitberry reason=4xx status=%d agent=%s body=%s',
                         rid, upstream.status_code, agent_id, _safe_body_preview(upstream))
        return jsonify({'error': 'upstream_error', 'message': f'BitBerry returned HTTP {upstream.status_code}.'}), 502

    if not stream:
        try:
            data = upstream.json()
        except ValueError:
            _diag_log.error('rid=%s side=bitberry reason=non_json_response agent=%s body=%s',
                             rid, agent_id, _safe_body_preview(upstream))
            return jsonify({'error': 'backend_failure', 'message': 'BitBerry returned a non-JSON response.'}), 502
        content = (
            data.get('choices', [{}])[0]
                .get('message', {})
                .get('content', '')
        )
        if not content.strip():
            _diag_log.warning('rid=%s side=bitberry reason=empty_content agent=%s response_keys=%s',
                               rid, agent_id, list(data.keys()))
        _timing_log.info('rid=%s response_complete agent=%s elapsed_ms=%d', rid, agent_id, elapsed_ms())
        return jsonify({'content': content})

    # Streaming: relay BitBerry's SSE-style chunks to the browser as they
    # arrive, so the reply renders incrementally instead of waiting for the
    # whole response.
    def relay():
        import json as _json
        first_chunk_logged = False
        line_count = 0
        content_seen = False
        ended_on_tool_calls = False
        sample_lines = []  # first few raw 'data:' lines, for diagnostics only
        try:
            for line in upstream.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                line_count += 1
                if not first_chunk_logged:
                    first_chunk_logged = True
                    _timing_log.info('rid=%s first_chunk_relayed agent=%s elapsed_ms=%d', rid, agent_id, elapsed_ms())

                # Peek at whether this event actually carries renderable
                # content, without altering what gets relayed to the
                # browser — the browser's own parser is the source of truth
                # for rendering, this is purely so a shape mismatch between
                # what BitBerry sends and what the client expects shows up
                # in the log instead of silently producing an empty reply.
                stripped = line.strip()
                if stripped.startswith('data:'):
                    raw = stripped[5:].strip()
                    if len(sample_lines) < 5:
                        sample_lines.append(raw[:200])
                    if raw and raw != '[DONE]':
                        try:
                            evt = _json.loads(raw)
                            choice = (evt.get('choices') or [{}])[0]
                            delta_content = (choice.get('delta') or {}).get('content')
                            msg_content = (choice.get('message') or {}).get('content')
                            if delta_content or msg_content:
                                content_seen = True
                            if choice.get('finish_reason') == 'tool_calls':
                                ended_on_tool_calls = True
                        except (ValueError, AttributeError, IndexError):
                            pass

                yield line + '\n'
        except req.exceptions.ChunkedEncodingError as e:
            # BitBerry's connection dropped mid-stream (as opposed to
            # finishing normally) — distinct from a clean end so this isn't
            # confused with "the agent just had nothing more to say".
            _diag_log.error('rid=%s side=bitberry reason=stream_dropped agent=%s lines_received=%d error=%s',
                             rid, agent_id, line_count, e)
            yield 'data: {"error": "network_error"}\n\n'
        except req.exceptions.RequestException as e:
            _diag_log.error('rid=%s side=network reason=%s agent=%s lines_received=%d error=%s',
                             rid, type(e).__name__, agent_id, line_count, e)
            yield 'data: {"error": "network_error"}\n\n'
        finally:
            if line_count == 0:
                # BitBerry answered (status was already checked as
                # non-error above) but closed the stream without sending a
                # single SSE line — this is the "hangs forever with nothing
                # rendered" shape from the client's point of view, and it's
                # on BitBerry's side, not this proxy's relay loop.
                _diag_log.error('rid=%s side=bitberry reason=empty_stream agent=%s elapsed_ms=%d',
                                 rid, agent_id, elapsed_ms())
            elif not content_seen and ended_on_tool_calls:
                # Confirmed, reproducible BitBerry-side dead-end: the model
                # decided to call a tool (finish_reason=tool_calls) and the
                # stream ends right there — BitBerry never executes the
                # tool or sends a follow-up assistant turn with its result.
                # Distinct from other empty-content cases because the fix
                # belongs entirely to whoever owns BitBerry's tool-calling
                # loop, not this proxy (which only relays, it doesn't run
                # tools or continue the conversation on BitBerry's behalf).
                _diag_log.error('rid=%s side=bitberry reason=tool_call_not_resolved agent=%s '
                                 'lines_received=%d sample=%s', rid, agent_id, line_count, sample_lines)
                yield 'data: {"pos_error": "tool_call_not_resolved"}\n\n'
            elif not content_seen:
                # BitBerry sent SSE lines, but none of them had a
                # choices[0].delta.content or .message.content the client
                # can render, for some other reason than the tool-call
                # dead-end above — e.g. a response shape this proxy doesn't
                # recognize yet. This is the "empty answer, no proxy error"
                # shape — check side=bitberry: the shape BitBerry sent.
                _diag_log.error('rid=%s side=bitberry reason=no_renderable_content agent=%s '
                                 'lines_received=%d sample=%s', rid, agent_id, line_count, sample_lines)
            upstream.close()
            _timing_log.info('rid=%s stream_complete agent=%s lines=%d content_seen=%s elapsed_ms=%d',
                              rid, agent_id, line_count, content_seen, elapsed_ms())

    return Response(
        stream_with_context(relay()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'X-Request-Id': rid},
    )


@chat_bp.route('/api/reauth-check', methods=['GET'])
@login_required
def api_reauth_check():
    """Lightweight status check the chat UI can poll after bouncing through
    silent reauth, to confirm the session now has a usable token."""
    status, _ = _google_token_status()
    return jsonify({'status': status})
