# aingram/cc_hook/format.py
from __future__ import annotations

import os
from typing import Any
from xml.sax.saxutils import escape as xml_escape

_ATTR_ENTITIES = {'"': '&quot;', "'": '&apos;'}


def _attr_escape(s: str) -> str:
    """Escape for double-quoted XML attributes (always emit &quot; for quotes)."""
    return xml_escape(s, _ATTR_ENTITIES)


def _project_basename(project_path: str | None) -> str | None:
    if not project_path:
        return None
    # handle both forward and back slashes cross-platform
    normalized = project_path.replace('\\', '/').rstrip('/')
    name = os.path.basename(normalized)
    return name or None


def _short_date(created_at: str | None) -> str:
    if not created_at:
        return ''
    return created_at.split('T', 1)[0]


def format_memory_block(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ''
    lines = ['<aingram-memory>']
    for e in entries:
        score = float(e.get('score', 0.0))
        attrs = [
            f'id="{_attr_escape(str(e.get("entry_id", "")))}"',
            f'score="{_attr_escape(f"{score:.2f}")}"',
        ]
        # Absolute cosine relevance (0–1) — display-only; lets the reader tell a strong
        # match (~0.7) from a tangential one (~0.45), which the RRF score cannot convey.
        relevance = e.get('relevance')
        if relevance is not None:
            attrs.append(f'relevance="{_attr_escape(f"{float(relevance):.2f}")}"')
        attrs += [
            f'type="{_attr_escape(str(e.get("entry_type", "")))}"',
            f'created="{_attr_escape(_short_date(e.get("created_at")))}"',
        ]
        project = _project_basename(e.get('project_path'))
        if project is not None:
            attrs.append(f'project="{_attr_escape(project)}"')
        content = str(e.get('content', ''))
        lines.append(f'  <entry {" ".join(attrs)}>')
        lines.append(f'    <content>{xml_escape(content)}</content>')
        lines.append('  </entry>')
    lines.append('</aingram-memory>')
    return '\n'.join(lines) + '\n'
