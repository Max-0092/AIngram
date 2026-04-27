# aingram/cc_hook/config.py
from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({'1', 'true', 'yes', 'on'})


@dataclass
class HookConfig:
    enabled: bool = True
    db_path: str | None = None  # None → MemoryStore default path
    daemon_host: str = '127.0.0.1'
    daemon_port: int = 7750
    hook_timeout_ms: int = 2000
    idle_shutdown_seconds: float = 30 * 60

    prompt_limit: int = 8
    # Score thresholds are calibrated for the composite score returned by
    # MemoryStore.recall(): rrf_score * importance * confidence * recency.
    # With RRF k=60 across ≤4 ranked lists the composite ceiling is ≈0.066
    # (4/61), and typical strong matches land in 0.008–0.015. Thresholds /
    # boost / demote are scaled to that range. Override via hook.toml if you
    # want stricter filtering.
    prompt_score_threshold: float = 0.005
    edit_limit: int = 3
    edit_score_threshold: float = 0.007
    tool_matchers: list[str] = field(default_factory=lambda: ['Edit', 'Write', 'NotebookEdit'])

    project_boost: float = 0.003
    seen_demote: float = 0.004

    seen_cache_dir: str = '~/.aingram/hook-seen'
    seen_cap: int = 200
    stale_days: int = 7


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.warning('could not read %s: %s', path, e)
        return {}


def _apply_toml(cfg: HookConfig, data: dict[str, Any]) -> HookConfig:
    top_level_map = {
        'enabled': 'enabled',
        'db_path': 'db_path',
        'daemon_host': 'daemon_host',
        'daemon_port': 'daemon_port',
        'hook_timeout_ms': 'hook_timeout_ms',
    }
    for key, attr in top_level_map.items():
        if key in data:
            setattr(cfg, attr, data[key])

    if 'idle_shutdown_minutes' in data:
        cfg.idle_shutdown_seconds = float(data['idle_shutdown_minutes']) * 60

    triggers = data.get('triggers', {})
    ups = triggers.get('user_prompt_submit', {})
    if 'limit' in ups:
        cfg.prompt_limit = int(ups['limit'])
    if 'score_threshold' in ups:
        cfg.prompt_score_threshold = float(ups['score_threshold'])
    ptu = triggers.get('pre_tool_use', {})
    if 'limit' in ptu:
        cfg.edit_limit = int(ptu['limit'])
    if 'score_threshold' in ptu:
        cfg.edit_score_threshold = float(ptu['score_threshold'])
    if 'tool_matchers' in ptu and isinstance(ptu['tool_matchers'], list):
        cfg.tool_matchers = [str(m) for m in ptu['tool_matchers']]

    scoring = data.get('scoring', {})
    if 'project_boost' in scoring:
        cfg.project_boost = float(scoring['project_boost'])
    if 'seen_demote' in scoring:
        cfg.seen_demote = float(scoring['seen_demote'])

    session = data.get('session', {})
    if 'seen_cache_dir' in session:
        cfg.seen_cache_dir = str(session['seen_cache_dir'])
    if 'seen_cap' in session:
        cfg.seen_cap = int(session['seen_cap'])
    if 'stale_days' in session:
        cfg.stale_days = int(session['stale_days'])

    return cfg


def _apply_env(cfg: HookConfig, env: dict[str, str]) -> HookConfig:
    if v := env.get('AINGRAM_HOOK_DISABLED'):
        if v.strip().lower() in _TRUTHY:
            cfg.enabled = False
    if v := env.get('AINGRAM_HOOK_DB_PATH'):
        cfg.db_path = v
    if v := env.get('AINGRAM_HOOK_PROMPT_LIMIT'):
        cfg.prompt_limit = int(v)
    if v := env.get('AINGRAM_HOOK_EDIT_LIMIT'):
        cfg.edit_limit = int(v)
    if v := env.get('AINGRAM_HOOK_PROJECT_BOOST'):
        cfg.project_boost = float(v)
    if v := env.get('AINGRAM_HOOK_TIMEOUT_MS'):
        cfg.hook_timeout_ms = int(v)
    return cfg


def load_hook_config(
    *,
    toml_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> HookConfig:
    """Load defaults → ~/.aingram/hook.toml → env vars (highest precedence)."""
    if toml_path is None:
        toml_path = Path('~/.aingram/hook.toml').expanduser()
    cfg = HookConfig()
    cfg = _apply_toml(cfg, _load_toml(toml_path))
    cfg = _apply_env(cfg, env if env is not None else dict(os.environ))
    return cfg
