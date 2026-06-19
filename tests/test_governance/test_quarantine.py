import pytest

from aingram.governance.quarantine import default_status_for_caller
from aingram.security.roles import Role


class _Caller:
    def __init__(self, role):
        self.role = role


def test_admin_caller_is_approved():
    assert default_status_for_caller(_Caller(Role.ADMIN)) == 'approved'


@pytest.mark.parametrize('role', [Role.CONTRIBUTOR, Role.READER])
def test_non_admin_caller_is_quarantined(role):
    assert default_status_for_caller(_Caller(role)) == 'pending'


def test_unauthenticated_caller_is_quarantined():
    assert default_status_for_caller(None) == 'pending'
