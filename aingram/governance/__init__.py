"""Memory v2 governance layer — quarantine, trust scoring, secret scanning.

A clean, namespaced extension of the fork's existing ``security``/``trust``
machinery (one reviewable diff vs upstream). sf1 freezes these names/types;
sf2 stores them, sf3/sf4 populate and read them, sf7 governs against them.
"""

from __future__ import annotations

from aingram.governance.quarantine import default_status_for_caller

__all__ = ['default_status_for_caller']
