"""Block-on-hit secret scanner (extends the fork's redaction pattern set).

``capture/filters.py`` *redacts* secrets into chat logs; a governed store must
*refuse* an entry carrying a hard secret, not store a redacted husk. We reuse
the fork's redaction patterns as a floor and add hard-secret patterns the
default set misses.
"""

from __future__ import annotations

import re

from aingram.capture.config import _default_redaction_patterns

# Extend the fork's redaction set with our hard-secret patterns.
_EXTRA = {
    'anthropic': r'sk-ant-[A-Za-z0-9_-]{20,}',
    'supabase':  r'SUPABASE_KEY\s*=\s*ey[A-Za-z0-9_-]+',
    # R2/S3 secret-key: anchored to the *_SECRET_*_KEY= assignment context, NEVER a bare length run.
    # A bare {40,} base64/hex run matches every 64-hex content_hash and every base64 signature, and
    # any hit hard-zeros trust (trust.py) -> it would force-quarantine our own provenance-bearing
    # memory (a self-DoS). Anchoring to the assignment keyword is what keeps the scanner safe.
    'r2_secret': r'(?:R2|AWS)_SECRET(?:_ACCESS)?_KEY\s*[=:]\s*[\'"]?[A-Za-z0-9/+]{40,}',
}
_PATTERNS = {f'redaction_{i}': p for i, p in enumerate(_default_redaction_patterns())} | _EXTRA
_COMPILED = {name: re.compile(p) for name, p in _PATTERNS.items()}


def scan_for_secrets(text: str) -> list[str]:
    """Return names of secret patterns found in ``text`` (empty list = clean)."""
    return [name for name, rx in _COMPILED.items() if rx.search(text or '')]
