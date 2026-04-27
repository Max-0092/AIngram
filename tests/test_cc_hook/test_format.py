# tests/test_cc_hook/test_format.py
from __future__ import annotations

import re

from aingram.cc_hook.format import format_memory_block


def _entry(
    eid='abc',
    score=0.42,
    content='hello world',
    entry_type='lesson',
    created_at='2026-04-14T10:00:00Z',
    project_path=None,
):
    return {
        'entry_id': eid,
        'score': score,
        'content': content,
        'entry_type': entry_type,
        'created_at': created_at,
        'project_path': project_path,
    }


def test_empty_list_returns_empty_string() -> None:
    assert format_memory_block([]) == ''


def test_single_entry_renders_well_formed_block() -> None:
    out = format_memory_block([_entry()])
    assert out.startswith('<aingram-memory>')
    assert out.rstrip().endswith('</aingram-memory>')
    assert 'id="abc"' in out
    assert 'score="0.42"' in out
    assert 'type="lesson"' in out
    assert 'hello world' in out


def test_content_rendered_verbatim() -> None:
    # format_memory_block does not truncate — content capping is ranking's job
    long_content = 'x' * 1000
    out = format_memory_block([_entry(content=long_content)])
    m = re.search(r'<content>(.*?)</content>', out, re.DOTALL)
    assert m is not None
    assert m.group(1) == long_content


def test_xml_unsafe_chars_escaped() -> None:
    out = format_memory_block([_entry(content='a & b < c > d "quoted" \'single\'')])
    assert '&amp;' in out
    assert '&lt;' in out
    assert '&gt;' in out
    # content body does not HTML-escape quotes; attributes do. Verify no raw '<' leaks mid-content.
    assert '< c' not in out
    assert '> d' not in out


def test_multiple_entries_preserve_order() -> None:
    entries = [_entry(eid='a'), _entry(eid='b'), _entry(eid='c')]
    out = format_memory_block(entries)
    assert out.index('id="a"') < out.index('id="b"') < out.index('id="c"')


def test_project_path_extracts_basename_attribute() -> None:
    out = format_memory_block([_entry(project_path='D:\\Misc\\GitHub\\portfolio\\AIngram')])
    assert 'project="AIngram"' in out


def test_missing_project_path_omits_attribute() -> None:
    out = format_memory_block([_entry(project_path=None)])
    assert 'project=' not in out


def test_created_at_shortened_to_date() -> None:
    out = format_memory_block([_entry(created_at='2026-04-14T10:00:00.123Z')])
    assert 'created="2026-04-14"' in out


def test_attribute_quotes_escaped_in_attribute() -> None:
    out = format_memory_block([_entry(entry_type='weird"type')])
    assert '&quot;' in out
