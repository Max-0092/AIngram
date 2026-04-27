"""Single-file entry point for Claude Code hook registration.

This file is the target of `aingram hook install` — the installer writes
its absolute path into ~/.claude/settings.json. Keep this file tiny and
stable; actual logic lives in aingram.cc_hook.main.
"""

from aingram.cc_hook.main import main

if __name__ == '__main__':
    main()
