# Honesty check: the real operator round-trip, not fixture-injected pins.
# remember -> pin(admin) -> the entry appears in core_memory with NO query;
# a pending entry is refused at pin() and never reaches core memory.
import pytest

from aingram.core_tier import core_memory, pin


def test_pinned_entry_appears_in_core_memory_without_a_query(store, admin_caller):
    eid = store.remember('the canonical deploy runbook')
    store._engine.set_governance(eid, status='approved', trust_score=0.9)

    assert core_memory(store) == []          # nothing pinned yet

    pin(store, eid, caller=admin_caller)     # the real operator gate

    items = core_memory(store)
    assert [i['entry_id'] for i in items] == [eid]
    assert items[0]['role'] == 'data'
    assert items[0]['content'] == 'the canonical deploy runbook'


def test_ineligible_entry_is_refused_and_never_injected(store, admin_caller):
    eid = store.remember('an unreviewed claim')   # status defaults to 'pending'

    with pytest.raises(ValueError):
        pin(store, eid, caller=admin_caller)

    assert eid not in {i['entry_id'] for i in core_memory(store)}
