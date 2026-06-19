# tests/test_storage/test_entry_object_model.py
# The v10 governance/trust/temporal columns must be readable through MemoryEntry.
# sf2 added the columns to the table; this wires them into the Python object model
# so the parallel cluster (sf3 recall, sf4 capture, sf7 core tier) reads one stable
# MemoryEntry instead of each editing types.py + engine.py (the shared chokepoint).
from aingram.storage.engine import StorageEngine
from aingram.types import AgentSession


def _engine(tmp_path):
    eng = StorageEngine(str(tmp_path / 'test.db'))
    eng.store_session(
        AgentSession(
            session_id='s1',
            agent_name='test-agent',
            public_key='a' * 64,
            created_at='2026-01-01T00:00:00+00:00',
        )
    )
    return eng


def _store(eng, entry_id='e1'):
    eng.store_entry(
        entry_id=entry_id,
        content_hash='ch1',
        entry_type='observation',
        content='{"text":"hello"}',
        session_id='s1',
        sequence_num=1,
        prev_entry_id=None,
        signature='sig1',
        created_at='2026-01-01T00:00:00+00:00',
        embedding=[0.1] * 768,
    )


def test_fresh_entry_exposes_governance_defaults(tmp_path):
    # A plain write takes the schema defaults: quarantine-by-default + unscored + valid-now.
    eng = _engine(tmp_path)
    _store(eng)
    entry = eng.get_entry('e1')
    assert entry is not None
    assert entry.status == 'pending'      # NOT NULL DEFAULT 'pending'
    assert entry.trust_score is None      # unscored -> recall ranks neutral 0.5
    assert entry.valid_from is None
    assert entry.valid_to is None         # currently valid
    assert entry.pinned == 0              # NOT NULL DEFAULT 0
    assert entry.kind is None
    assert entry.source is None
    assert entry.domain is None
    assert entry.scope is None
    eng.close()


def test_governance_columns_round_trip_through_object(tmp_path):
    # Once governance writes land (sf4), the read path must surface real values, not just defaults.
    eng = _engine(tmp_path)
    _store(eng)
    eng._conn.execute(
        "UPDATE memory_entries SET kind='fact', source='operator', domain='pipeline', "
        "scope='project', status='approved', trust_score=0.87, "
        "valid_from='2026-01-01T00:00:00+00:00', valid_to='2026-06-01T00:00:00+00:00', "
        "pinned=1 WHERE entry_id='e1'"
    )
    eng._conn.commit()
    entry = eng.get_entry('e1')
    assert entry.kind == 'fact'
    assert entry.source == 'operator'
    assert entry.domain == 'pipeline'
    assert entry.scope == 'project'
    assert entry.status == 'approved'
    assert entry.trust_score == 0.87
    assert entry.valid_from == '2026-01-01T00:00:00+00:00'
    assert entry.valid_to == '2026-06-01T00:00:00+00:00'
    assert entry.pinned == 1
    eng.close()


def test_get_entries_by_ids_also_exposes_governance(tmp_path):
    # The batch read path used by recall must map the columns too, not just get_entry.
    eng = _engine(tmp_path)
    _store(eng, 'e1')
    eng._conn.execute("UPDATE memory_entries SET trust_score=0.5, status='approved' WHERE entry_id='e1'")
    eng._conn.commit()
    rows = eng.get_entries_by_ids(['e1'])
    assert len(rows) == 1
    assert rows[0].trust_score == 0.5
    assert rows[0].status == 'approved'
    eng.close()


def test_set_governance_writes_only_provided_fields(tmp_path):
    # The write-twin of the read path: policy layers (sf4 capture, sf7 pin, sf6 consolidation)
    # set governance columns through one parameterized mechanism. None = leave untouched.
    eng = _engine(tmp_path)
    _store(eng)
    eng.set_governance('e1', source='codex', kind='fact', trust_score=0.9, status='approved')
    entry = eng.get_entry('e1')
    assert entry.source == 'codex'
    assert entry.kind == 'fact'
    assert entry.trust_score == 0.9
    assert entry.status == 'approved'
    # Unprovided fields keep their defaults (not clobbered to NULL).
    assert entry.pinned == 0
    assert entry.domain is None
    eng.close()


def test_set_governance_no_fields_is_a_noop(tmp_path):
    eng = _engine(tmp_path)
    _store(eng)
    eng.set_governance('e1')  # nothing provided
    entry = eng.get_entry('e1')
    assert entry.status == 'pending'
    assert entry.trust_score is None
    eng.close()


def test_set_governance_can_pin(tmp_path):
    eng = _engine(tmp_path)
    _store(eng)
    eng.set_governance('e1', pinned=1)
    assert eng.get_entry('e1').pinned == 1
    eng.set_governance('e1', pinned=0)
    assert eng.get_entry('e1').pinned == 0
    eng.close()
