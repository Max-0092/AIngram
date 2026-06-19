import json
import sqlite3

import sqlite_vec

from aingram.governance.backfill import backfill_governance_columns
from aingram.storage.schema import apply_schema


def _conn(tmp_path):
    c = sqlite3.connect(str(tmp_path / 'b.db'))
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    apply_schema(c, enable_vec=True)
    c.execute("INSERT INTO agent_sessions (session_id,agent_name,public_key,created_at) "
              "VALUES ('s1','t','pk','2026-01-01')")
    return c


def test_backfill_maps_metadata_and_curates(tmp_path):
    c = _conn(tmp_path)
    meta = json.dumps({'kind': 'fact', 'source': 'operator', 'domain': 'pipeline', 'scope': 'project'})
    c.execute("INSERT INTO memory_entries (entry_id,content_hash,entry_type,content,session_id,"
              "sequence_num,signature,created_at,importance,metadata) "
              "VALUES ('e1','ch','observation','{}','s1',1,'sig','2026-01-02',0.5,?)", (meta,))
    n = backfill_governance_columns(c)
    assert n == 1
    row = c.execute("SELECT kind,source,domain,scope,status,trust_score,valid_from,valid_to "
                    "FROM memory_entries WHERE entry_id='e1'").fetchone()
    assert row == ('fact', 'operator', 'pipeline', 'project', 'approved', 1.0, '2026-01-02', None)
    c.close()


def test_backfill_is_idempotent(tmp_path):
    c = _conn(tmp_path)
    c.execute("INSERT INTO memory_entries (entry_id,content_hash,entry_type,content,session_id,"
              "sequence_num,signature,created_at,importance,metadata) "
              "VALUES ('e1','ch','observation','{}','s1',1,'sig','2026-01-02',0.5,'{}')")
    assert backfill_governance_columns(c) == 1
    assert backfill_governance_columns(c) in (0, 1)   # re-run safe, no corruption
    assert c.execute("SELECT status FROM memory_entries WHERE entry_id='e1'").fetchone()[0] == 'approved'
    c.close()


def test_backfill_does_not_flip_a_governed_decision(tmp_path):
    # A post-governance re-run must NOT revive a denied entry to approved.
    c = _conn(tmp_path)
    c.execute("INSERT INTO memory_entries (entry_id,content_hash,entry_type,content,session_id,"
              "sequence_num,signature,created_at,importance,metadata,status) "
              "VALUES ('e1','ch','observation','{}','s1',1,'sig','2026-01-02',0.5,'{}','denied')")
    backfill_governance_columns(c)
    assert c.execute("SELECT status FROM memory_entries WHERE entry_id='e1'").fetchone()[0] == 'denied'
    c.close()
