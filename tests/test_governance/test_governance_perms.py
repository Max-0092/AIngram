import pytest

from aingram.exceptions import AuthorizationError
from aingram.security.roles import PERMISSIONS, Role, RoleAuthorizer


class _Caller:
    def __init__(self, role, session_id='s'):
        self.role = role
        self.session_id = session_id


@pytest.mark.parametrize('op', ['approve', 'deny', 'pin', 'unpin'])
def test_only_admin_may_govern(op):
    assert PERMISSIONS[op] == {Role.ADMIN}
    RoleAuthorizer().check(_Caller(Role.ADMIN), op)            # no raise
    with pytest.raises(AuthorizationError):
        RoleAuthorizer().check(_Caller(Role.CONTRIBUTOR), op)
