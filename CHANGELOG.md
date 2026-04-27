# Changelog

## Unreleased

- **Claude Code hook integration** (`aingram hook install`): AIngram can now inject relevant memories as context into Claude Code before every prompt and before file edits. Patches `~/.claude/settings.json` to register a non-blocking `UserPromptSubmit` / `PreToolUse` hook. Memories appear as `<aingram-memory>` XML blocks in the Claude Code context. Uninstall with `aingram hook uninstall`.
- **Recall daemon** (`aingram recall-daemon start|stop|status`): a persistent loopback HTTP server on `localhost:7750` that wraps `MemoryStore.recall`. Pre-warms the ONNX JIT kernel on startup for consistent sub-2s hook responses. Idles down automatically after 30 minutes without traffic. The hook auto-spawns the daemon if it is not running.
- **Hook config** (`~/.aingram/hook.toml`): controls `project_boost` (prefer memories from the current working directory), `seen_demote` (reduce weight of already-surfaced memories), per-event `limit` / `score_threshold`, and seen-set deduplication (prevents the same memory from being re-injected every turn). Override via `AINGRAM_HOOK_DISABLED`, `AINGRAM_HOOK_PROMPT_LIMIT`, `AINGRAM_HOOK_EDIT_LIMIT`, `AINGRAM_HOOK_PROJECT_BOOST`, `AINGRAM_HOOK_TIMEOUT_MS`.
- **`python -m aingram`**: the package can now be invoked as `python -m aingram <subcommand>` in addition to the `aingram` console script.
- **Wheel includes `aingram_cc_hook.py`**: the hook entry-point shim is bundled in the wheel via `force-include` so `aingram hook install` works correctly after a `pip install`.
- **Capture drain startup consolidation:** `CaptureDrain` now checks the unconsolidated entry backlog at startup and pre-seeds the consolidation counter from the DB; if the backlog already meets the threshold (e.g. entries accumulated while the daemon was stopped), consolidation fires immediately rather than waiting for the next drain cycle.
- **Capture filters:** empty-record check now passes through records that carry `tool_calls` data even when `user_prompt` and `assistant_response` are absent; previously those records were silently dropped.
- **Ollama thinking-model support:** `LocalExtractor` sends `options.think=false` to Ollama, disabling the reasoning pass on models that support it (e.g. DeepSeek-R1 variants). Handles the empty-`response` case those models can produce gracefully.
- **Storage:** added `get_incomplete_task_count()` (counts `pending` + `claimed` tasks, for polling until all work is truly complete) and `rerank_by_vector()` (semantic alias for `search_vectors_filtered`, used by the QJL two-pass pipeline).

## 1.2.2

- **Capture filters:** drop low-substance turns when there are no `tool_calls` and combined prompt + response text is shorter than 40 characters (after resolving JSON `{"text":...}` wrappers).
- **Capture queue:** skip enqueueing when the same `user_prompt` was already queued within the last 5 minutes (`insert` returns `None`); reduces duplicate backlog from repeated hooks.
- **Contradiction detection:** cap total entry pairs evaluated per `consolidate()` run at 200 (still at most 50 per entity); remainder is deferred with an info log.
- **Storage:** `get_entity_entry_pairs()` now returns only mentions for **non-consolidated** entries, so contradiction passes ignore superseded graph noise.

## 1.2.1

Patch release after 1.2.0: contradiction detection backends, capture daemon improvements, adapter/schema updates, and a CLI startup fix.

- **DeBERTa-v3 contradiction detection:** local NLI-based contradiction classifier (`contradiction_backend = "deberta"`) using DeBERTa-v3-base exported to ONNX (~740MB, cached locally). No LLM or network call required at inference time. Detects contradicting memory pairs grouped by entity and marks the older entry as superseded. Falls back to recency when the model cannot determine which entry wins.
- **LLM contradiction backend:** `contradiction_backend = "llm"` routes contradiction classification through Ollama (requires `aingram[llm]`). Both backends implement the new `ContradictionClassifier` protocol — swap without touching orchestration code.
- **`ContradictionClassifier` protocol:** strategy-pattern interface (`classify(text_a, text_b) -> ContradictionVerdict`) in `aingram/processing/protocols.py`. `ContradictionVerdict` dataclass added to `aingram/types.py`.
- **GLiNER2 model upgrade:** entity extractor default changed from `urchade/gliner_medium-v2.1` to `knowledgator/gliner-multitask-large-v0.5` (205M params, multitask). Minimum `gliner` package version bumped to `>=0.2.0`.
- **Capture daemon auto-consolidation:** `CaptureDrain` triggers `store.consolidate()` automatically every N successfully ingested records. Configured via `consolidation_interval_records` in `[capture]` config (default: 50, 0 = disabled).
- **`CaptureQueue.last_capture_times()`:** per-tool last capture timestamps from the persistent queue DB. The `/status` endpoint now uses this instead of in-memory health-check values, so timestamps survive daemon restarts.
- **Claude Code hook format:** `ClaudeCodeAdapter` handles both native hook payloads (`UserPromptSubmit`, `PostToolUse`) and the legacy direct-POST format. `PostToolUse` records store full `tool_input` in `tool_calls`.
- **Gemini CLI / Cursor adapters:** updated field names to match current hook schemas.
- **Config:** `AIngramConfig` extended with `contradiction_backend` and `contradiction_threshold`. `CaptureConfig` extended with `consolidation_interval_records`. All fields supported via env vars and `config.toml`.
- **Fix — `aingram capture on/off`:** commands crashed at startup with `TypeError: 'default' is not supported for nargs=-1`. Fixed by changing to `list[str] | None = typer.Argument(default=None)`.
- **Tests:** `test_store_v3` `MemoryStore` fixture now uses an explicit `AIngramConfig()` so consolidation and related tests do not pick up `contradiction_backend` (or other values) from `~/.aingram/config.toml` or the environment.

## 1.2.0

- **Capture daemon:** opt-in local HTTP daemon (`aingram[capture]`) that captures prompt/response pairs from seven AI coding tools (Claude Code, Cursor, Gemini CLI, Aider, Copilot, Cline, ChatGPT) and writes them into AIngram memory. Includes per-tool adapters, `@nocapture` opt-out, secret redaction, toggle system, and CLI subcommands (`aingram capture start|stop|status|on|off|install`). Disabled by default; configure via `[capture]` in `config.toml` or `AINGRAM_CAPTURE_ENABLED` env var.
- **Config:** `AIngramConfig` extended with `capture: CaptureConfig | None` field; `_merge_toml_into()` parses `[capture]` TOML sections; `_merge_env_into()` reads `AINGRAM_CAPTURE_ENABLED` and `AINGRAM_CAPTURE_PORT`.
- **Multi-agent example:** `examples/05_multi_agent_shared_memory.py` — self-contained ~100-line demo of three async agents sharing one `MemoryStore` for concurrent hyperparameter exploration with piggyback recall.
- **Example smoke test:** `tests/test_examples.py` added to CI matrix; guards example scripts against bit-rot.
- **README:** new "Multi-agent patterns" and "Capture Daemon" sections; updated install extras to include `[capture]`.
- **Fix:** `aingram.__version__` corrected from `'1.0.0'` to `'1.1.0'` (was not bumped alongside `pyproject.toml` in the 1.1.0 release).

## 1.1.0

### Search, vectors, and packaging

- **Schema v9 (migrates from v8):** int8 quantization replaced by **QJL 1-bit** auxiliary vectors in `vec_entries_qjl`, dual-written with float32 `vec_entries` for coarse Hamming search plus float re-ranking.
- **Recall / vector search:** FTS5 **pre-filter** path with configurable `fts_prefilter_threshold`; when the candidate set is large enough, cosine re-ranking runs in Python over FTS hits (workaround for sqlite-vec `MATCH` + `IN` limits). **QJL two-pass** recall for large stores (coarse QJL KNN, then float re-rank).
- **GPU (optional):** `[project.optional-dependencies] gpu` — CUDA 12 pip wheels for ONNX Runtime GPU; README documents `onnxruntime` vs `onnxruntime-gpu` and `AINGRAM_ONNX_PROVIDER`.
- **CLI telemetry (opt-out):** anonymous usage events (command name + version + install id); disable via `--no-telemetry`, `AINGRAM_TELEMETRY_ENABLED=false`, or `telemetry_enabled` in `~/.aingram/config.toml`. See README for details.
- **Docs:** `AGENTS.md` (coding-agent reference), `llms.txt` (consumer API summary); README updates for benchmarks and installation notes.

## 1.0.0

### AIngram Lite

First public release under Apache-2.0.

- `MemoryStore`: `remember`, `recall`, `get_context`, `reference`, `verify`, `consolidate`, reasoning chains, `compact`, `export_json`, `import_json`.
- Storage: SQLite + sqlite-vec + FTS5; schema version 7; signed entries and session chains.
- Optional extraction (`local` / Sonnet), background task worker for entity linking, knowledge graph traversal.
- Security: MCP-oriented middleware (auth, RBAC, bounds, rate limits) when using `aingram[mcp]`.
- Typer CLI: `setup`, `status`, `add`, `search`, `entities`, `graph`, `consolidate`, `compact`, `export`, `import`, `agent` subcommands.
- Layered config: `AIngramConfig`, environment variables, optional `~/.aingram/config.toml`.
