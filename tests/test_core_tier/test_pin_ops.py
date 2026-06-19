# Pin/unpin are operator-gated: admin-only (sf1 RBAC), eligibility-checked, and
# they write through the frozen engine.set_governance pinned column. A non-admin is
# refused with AuthorizationError (the frozen sf1 exception) — NOT stdlib PermissionError.
import pytest

from aingram.core_tier import pin, unpin
from aingram.exceptions import AuthorizationError


def test_admin_can_pin_approved_high_trust(store_with_approved_entry, admin_caller):
    store, eid = store_with_approved_entry
    pin(store, eid, caller=admin_caller)
    assert store._engine.get_entry(eid).pinned == 1


def test_non_admin_is_refused(store_with_approved_entry, reader_caller):
    store, eid = store_with_approved_entry
    with pytest.raises(AuthorizationError):
        pin(store, eid, caller=reader_caller)


def test_pending_entry_cannot_be_pinned(store_with_pending_entry, admin_caller):
    store, eid = store_with_pending_entry
    with pytest.raises(ValueError):
        pin(store, eid, caller=admin_caller)


def test_unpin_clears_flag(store_with_pinned_entry, admin_caller):
    store, eid = store_with_pinned_entry
    unpin(store, eid, caller=admin_caller)
    assert store._engine.get_entry(eid).pinned == 0
