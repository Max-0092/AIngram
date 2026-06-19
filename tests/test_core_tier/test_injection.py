# Core memory injects pinned entries into EVERY session regardless of query
# (the always-in-context tier). Items are spotlight-wrapped (role='data'),
# ordered trust-desc, and only pinned entries appear.
from aingram.core_tier import core_memory


def test_pinned_entries_inject_without_a_query(store_with_two_pinned):
    store = store_with_two_pinned
    items = core_memory(store)
    assert len(items) == 2
    assert all(i['role'] == 'data' for i in items)               # spotlighted
    assert items[0]['trust_score'] >= items[1]['trust_score']    # trust-desc


def test_unpinned_entries_are_absent(store_with_one_pinned_one_not):
    store, pinned_id, other_id = store_with_one_pinned_one_not
    ids = {i['entry_id'] for i in core_memory(store)}
    assert pinned_id in ids and other_id not in ids


def test_store_hook_delegates_to_core_memory(store_with_two_pinned):
    # The thin store.py hook is the production surface sf8 wires into the daemon.
    store = store_with_two_pinned
    assert store.core_memory() == core_memory(store)
