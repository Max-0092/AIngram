# aingram/cc_hook/main.py
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from aingram.cc_hook.client import DaemonClient, DaemonError
from aingram.cc_hook.config import HookConfig, load_hook_config
from aingram.cc_hook.format import format_memory_block
from aingram.cc_hook.query import derive_query
from aingram.cc_hook.seen import SeenStore

_LOG_PATH = Path('~/.aingram/hook.log').expanduser()


def _log(reason: str, **ctx) -> None:
    """One tab-separated line per event, timestamped.

    Successes log too (``recall_ok``) — the log existed for years as
    failures-only, which made the failure *rate* unknowable: 1000 logged
    timeouts is catastrophic at 1100 requests and noise at 100k.
    """
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open('a', encoding='utf-8') as f:
            parts = [time.strftime('%Y-%m-%dT%H:%M:%S%z'), reason]
            for k, v in ctx.items():
                parts.append(f'{k}={v!r}')
            f.write('\t'.join(parts) + '\n')
    except OSError:
        pass


def _default_spawn_daemon() -> None:
    """Fire-and-forget spawn of `aingram recall-daemon start`."""
    try:
        subprocess.Popen(
            [sys.executable, '-m', 'aingram', 'recall-daemon', 'start'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        _log('spawn_failed', err=str(e))


def _budget_for_event(event: str, cfg: HookConfig) -> tuple[int, float, float]:
    """Return ``(limit, score_threshold, relevance_threshold)`` for the event."""
    if event == 'UserPromptSubmit':
        return cfg.prompt_limit, cfg.prompt_score_threshold, cfg.prompt_relevance_threshold
    if event == 'PreToolUse':
        return cfg.edit_limit, cfg.edit_score_threshold, cfg.edit_relevance_threshold
    return 0, 1.0, 0.0  # unreachable if we already derived a query


def run(
    *,
    stdin: TextIO,
    stdout: TextIO,
    cfg: HookConfig,
    spawn_daemon: Callable[[], None] = _default_spawn_daemon,
) -> int:
    """Main hook entry. Always returns 0."""
    if not cfg.enabled:
        return 0

    try:
        raw = stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        _log('bad_payload', err=str(e))
        return 0

    session_id = str(payload.get('session_id') or 'default')
    cwd = payload.get('cwd')
    event = payload.get('hook_event_name')

    query = derive_query(payload)
    if query is None:
        return 0

    seen_store = SeenStore(cache_dir=Path(cfg.seen_cache_dir), cap=cfg.seen_cap)
    seen_store.cleanup_stale(stale_days=cfg.stale_days)
    seen = seen_store.read(session_id)

    limit, threshold, relevance_threshold = _budget_for_event(str(event), cfg)
    if limit <= 0:
        return 0

    client = DaemonClient(
        host=cfg.daemon_host, port=cfg.daemon_port, timeout_ms=cfg.hook_timeout_ms
    )
    t0 = time.monotonic()
    try:
        results = client.recall(
            query=query,
            limit=limit,
            score_threshold=threshold,
            relevance_threshold=relevance_threshold,
            cwd=cwd,
            seen_entry_ids=seen,
            project_boost=cfg.project_boost,
            seen_demote=cfg.seen_demote,
        )
    except DaemonError as e:
        err_str = str(e).lower()
        refused = 'refused' in err_str
        # On Windows, a closed port times out (~2s) before returning ECONNREFUSED,
        # so TimeoutError fires instead. Treat both as "daemon not running".
        timed_out = 'timed out' in err_str
        _log(
            'daemon_refused' if refused else 'daemon_error',
            event=event,
            session=session_id,
            ms=int((time.monotonic() - t0) * 1000),
            err=str(e),
        )
        if refused or timed_out:
            spawn_daemon()
        return 0

    # An empty result is still a served request — log it, or the ok/error ratio
    # undercounts exactly the quiet sessions where recall works fine.
    _log(
        'recall_ok',
        event=event,
        session=session_id,
        n=len(results),
        ms=int((time.monotonic() - t0) * 1000),
    )

    if not results:
        return 0

    seen_store.append(session_id, [str(r.get('entry_id')) for r in results])
    stdout.write(format_memory_block(results))
    return 0


def main() -> None:
    # Force UTF-8 on stdio. Claude Code invokes the hook as a piped child, and
    # on Windows that defaults sys.stdout.encoding to cp1252 — which cannot
    # encode emoji, CJK, box-drawing, or math symbols that routinely appear in
    # recalled memory entries. A failed write would surface as an uncaught
    # UnicodeEncodeError → non-zero exit → "non-blocking status code:
    # Traceback" in Claude Code's UI.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            try:
                reconfigure(encoding='utf-8', errors='replace')
            except (OSError, ValueError):
                pass

    # Swallow any remaining uncaught exception so Claude Code never sees a
    # traceback from a non-blocking hook. Log it quietly and exit 0.
    try:
        cfg = load_hook_config(env=dict(os.environ))
        exit_code = run(stdin=sys.stdin, stdout=sys.stdout, cfg=cfg)
    except Exception as e:
        _log('unhandled', err=f'{type(e).__name__}: {e}')
        exit_code = 0
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
