# aingram/recall_daemon/cli.py
from __future__ import annotations

import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import typer

from aingram.recall_daemon.server import RecallDaemon

app = typer.Typer(help='Manage the AIngram recall daemon.')

_PID_PATH = Path('~/.aingram/recall-daemon.pid').expanduser()


class PidFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, pid: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(str(pid), encoding='utf-8')

    def read(self) -> int | None:
        if not self._path.exists():
            return None
        try:
            return int(self._path.read_text(encoding='utf-8').strip())
        except (OSError, ValueError):
            return None

    def remove(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass

    def is_stale(self) -> bool:
        pid = self.read()
        if pid is None:
            return True
        if sys.platform == 'win32':
            # os.kill(pid, 0) on Windows calls TerminateProcess, killing the
            # process instead of just checking existence. Use OpenProcess with
            # PROCESS_QUERY_LIMITED_INFORMATION (0x1000) — read-only check.
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return False
            return True
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return True
        except OSError:
            return True
        return False


def _default_db_path() -> str:
    return str(Path('agent_memory.db').resolve())


def _load_store_and_config():
    from aingram import MemoryStore
    from aingram.cc_hook.config import load_hook_config

    cfg = load_hook_config(env=dict(os.environ))
    db = cfg.db_path or _default_db_path()
    store = MemoryStore(db)
    return store, cfg


@app.command('start')
def start() -> None:
    """Start the recall daemon in the foreground (invoke from a spawner)."""
    pid_file = PidFile(_PID_PATH)
    if not pid_file.is_stale():
        typer.echo('daemon already running', err=True)
        raise typer.Exit(code=1)
    pid_file.write(os.getpid())
    store, cfg = _load_store_and_config()
    daemon = RecallDaemon(
        store=store,
        host=cfg.daemon_host,
        port=cfg.daemon_port,
        idle_shutdown_seconds=cfg.idle_shutdown_seconds,
    )
    daemon.start()
    try:
        # block until monitor thread sets the shutdown event
        while not daemon._shutdown_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
        pid_file.remove()


@app.command('stop')
def stop() -> None:
    pid_file = PidFile(_PID_PATH)
    pid = pid_file.read()
    if pid is None:
        typer.echo('no pid file, daemon not running')
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        typer.echo('pid file stale, removing')
    pid_file.remove()


@app.command('status')
def status() -> None:
    pid_file = PidFile(_PID_PATH)
    pid = pid_file.read()
    if pid is None or pid_file.is_stale():
        typer.echo('stopped')
        raise typer.Exit(code=1)
    # query /health using default port (cannot be easily discovered otherwise)
    from aingram.cc_hook.config import load_hook_config

    cfg = load_hook_config(env=dict(os.environ))
    url = f'http://{cfg.daemon_host}:{cfg.daemon_port}/health'
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            typer.echo(f'running (pid={pid}): {resp.read().decode()}')
    except (urllib.error.URLError, OSError) as e:
        typer.echo(f'running (pid={pid}) but /health unreachable: {e}')
        raise typer.Exit(code=2)
