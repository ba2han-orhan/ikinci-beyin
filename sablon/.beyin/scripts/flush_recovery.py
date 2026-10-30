#!/usr/bin/env python3
"""Audit/reconcile flush debt; replay only captured requests with an unchanged source."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

import _portalock
import flush


def public_detail(detail):
    if not isinstance(detail, str):
        return None
    known = {'transcript-unavailable', 'transcript-read-failed', 'request-capture-failed',
             'retry-source-changed', 'stale-inflight-lock-free', 'summary-empty',
             'summary-schema-invalid', 'daily-append-failed', 'state-finalization-failed',
             'already-appended', 'appended', 'below-minimum-turns', 'karar-atla', 'flush-bos',
             'temporary-directory-inside-vault'}
    if detail in known or re.fullmatch(r'(?:claude|codex|antigravity)-(?:timeout|exec-error|cli-missing|exit-\d+)', detail):
        return detail
    # Unsupported config values and unexpected error messages can carry credentials.
    return 'other-error'


def owner_state(state):
    pid = state.get('pid')
    identity = state.get('owner')
    if not isinstance(pid, int) or pid <= 0 or not identity:
        return 'unknown'
    actual = flush._process_identity(pid)
    if actual:
        return 'running' if actual == identity else 'different-process'
    if Path('/proc').is_dir():
        return 'not-running'
    # Windows birth identity is unavailable: do not guess from a reused PID.
    return 'unknown'


def source_available(session_id, state_dir):
    request_path = flush._request_path(state_dir, session_id)
    if request_path.exists():
        request = flush._load_json_object(request_path, {})
        path = flush._resolve_transcript_path(request, session_id)
        if path and path.is_file():
            return True, 'captured-request'
    if flush._find_codex_transcript(session_id):
        return True, 'codex'
    if flush.CODEX_SESSION_ID.fullmatch(session_id):
        # Discovery only; legacy source existence does not prove a missing append.
        if any(p.is_file() for p in (Path.home() / '.claude/projects').glob('*/' + session_id + '.jsonl')):
            return True, 'claude-legacy'
    return False, 'unavailable'


def audit(state_dir, *, reconcile=False, now=None, stale_seconds=86400):
    state_dir = Path(state_dir)
    now = time.time() if now is None else now
    rows = []
    for path in sorted(state_dir.glob('flush-*.json')):
        if not re.fullmatch(r'flush-[0-9a-f]{64}\.json', path.name):
            continue
        state = flush._load_json_object(path, {})
        if state.get('status') not in ('inflight', 'fail', 'interrupted'):
            continue
        session_id = state.get('session_id')
        if not isinstance(session_id, str) or flush._session_state_path(state_dir, session_id) != path:
            rows.append({'key': path.stem[6:18], 'outcome': 'invalid-session-state'})
            continue
        with flush._session_lock_path(state_dir, session_id).open('a+') as lock, _portalock.exclusive(lock, blocking=False) as held:
            # Snapshot after acquiring: a worker may have finished between discovery and lock.
            if held:
                state = flush._load_json_object(path, {})
                if state.get('status') == 'ok':
                    continue
            owner = owner_state(state)
            found, kind = source_available(session_id, state_dir)
            age = now - state.get('ts', now)
            stale = state.get('status') == 'inflight' and age >= stale_seconds
            explanation = ('legacy-append-unknown' if kind == 'claude-legacy'
                           else 'source-available' if found else 'transcript-unavailable')
            changed = False
            if reconcile and held and stale and owner != 'running':
                previous = dict(state)
                state.update(status='interrupted', detail='stale-inflight-lock-free',
                             recovery={'reconciled_at': int(now), 'previous': previous,
                                       'owner_state': owner, 'source_kind': kind,
                                       'explanation': explanation})
                flush._atomic_write_json(path, state)
                changed = True
            rows.append({'key': path.stem[6:18], 'full_key': path.stem[6:], 'status': state.get('status'),
                         'detail': public_detail(state.get('detail')), 'age_hours': round(age / 3600, 1),
                         'lock': 'free' if held else 'held', 'owner': owner,
                         'source': kind, 'explanation': explanation, 'changed': changed})
    result = {'records': len(rows), 'changed': sum(r.get('changed', False) for r in rows),
              'unavailable': sum(r.get('source') == 'unavailable' for r in rows), 'rows': rows}
    if reconcile:
        flush._atomic_write_json(state_dir / 'flush-recovery-report.json', result)
    return result


def _current_checkpoint(session_id, source):
    transcript, _ = flush.format_turns(flush.read_transcript(source))
    return flush._checkpoint(session_id, transcript)


def _checkpoint_matches(state_dir, session_id, source):
    try:
        state = flush._load_json_object(flush._session_state_path(state_dir, session_id), {})
        stored = state.get('checkpoint')
        return isinstance(stored, str) and stored == _current_checkpoint(session_id, source)
    except (OSError, ValueError):
        return False


def retry(state_dir, key):
    """A legacy inflight cannot be safely replayed without a captured request."""
    if not re.fullmatch(r'[0-9a-f]{64}', key):
        raise ValueError('retry-key-invalid')
    state_dir = Path(state_dir)
    if state_dir.resolve() != flush.STATE_DIR.resolve():
        raise ValueError('retry-state-mismatch')
    request_path = state_dir / 'flush-requests' / f'{key}.json'
    if not request_path.is_file():
        return {'key': key[:12], 'outcome': 'legacy-request-unavailable'}
    with (state_dir / f'flush-{key}.lock').open('a+') as lock, _portalock.exclusive(lock, blocking=False) as held:
        if not held:
            return {'key': key[:12], 'outcome': 'worker-lock-held'}
        request = flush._load_json_object(request_path, {})
        sid = request.get('session_id')
        if not isinstance(sid, str) or hashlib.sha256(sid.encode()).hexdigest() != key:
            raise ValueError('retry-session-mismatch')
        reason = request.get('reason')
        runner = request.get('runner')
        if reason not in ('sessionend', 'precompact') or runner not in ('claude', 'codex', 'antigravity', 'agy'):
            raise ValueError('retry-metadata-invalid')
        source = flush._resolve_transcript_path(request, sid)
        if source is None:
            return {'key': key[:12], 'outcome': 'transcript-unavailable'}
        source_sha = flush._sha256(source)
        expected = request.get('source_sha256')
        if expected and source_sha != expected:
            # Claude Code çıkışta konuşma dışı satır ekleyebilir; checkpoint aynıysa replay güvenli.
            if not _checkpoint_matches(state_dir, sid, source):
                return {'key': key[:12], 'outcome': 'source-changed-since-request'}
        # Keep the session lock across validation AND replay. _flush_once knows it is held.
        args = argparse.Namespace(hook_input=request_path, reason=reason)
        previous_runner = os.environ.get('BEYIN_MODEL_RUNNER')
        os.environ['BEYIN_MODEL_RUNNER'] = runner
        try:
            event_time = dt.datetime.fromtimestamp(request['event_ts']).astimezone()
            flush._flush_once(args, event_time, lock_held=True, source_expected=source_sha)
        finally:
            if previous_runner is None:
                os.environ.pop('BEYIN_MODEL_RUNNER', None)
            else:
                os.environ['BEYIN_MODEL_RUNNER'] = previous_runner
        state = flush._load_json_object(flush._session_state_path(state_dir, sid), {})
        return {'key': key[:12], 'outcome': state.get('status'), 'detail': public_detail(state.get('detail'))}


def recover_dead_inflight(state_dir, *, stale_seconds=86400, budget=60.0):
    """Reconcile stale dead-PID inflight debt and replay its captured requests."""
    state_dir = Path(state_dir)
    report = audit(state_dir, reconcile=True, stale_seconds=stale_seconds)
    retried = []
    deadline = time.monotonic() + budget
    for row in report.get('rows', []):
        if not row.get('changed') or row.get('owner') == 'running':
            continue
        if time.monotonic() > deadline:
            break
        key = row.get('full_key')
        if not key:
            continue
        try:
            retried.append(retry(state_dir, key))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {'report': report, 'retried': retried}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=flush.STATE_DIR)
    parser.add_argument('--reconcile', action='store_true')
    parser.add_argument('--retry', metavar='SESSION_SHA256')
    args = parser.parse_args()
    if args.state.resolve() != flush.STATE_DIR.resolve() and args.retry:
        parser.error('Replay requires the vault runtime state directory')
    try:
        result = retry(args.state, args.retry) if args.retry else audit(args.state, reconcile=args.reconcile)
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': type(error).__name__}))
        raise SystemExit(1)
