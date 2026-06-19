import sqlite3

import pytest
import sqlite_vec

from aingram.storage.schema import SCHEMA_VERSION, apply_schema, get_schema_version

NEW_COLS = {'kind', 'source', 'domain', 'scope', 'status',
            'trust_score', 'valid_from', 'valid_to', 'pinned'}


def _conn(tmp_path):
    c = sqlite3.connect(str(tmp_path / 't.db'))
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    return c


def test_version_is_10():
    assert SCHEMA_VERSION == 10


def test_fresh_db_has_new_columns(tmp_path):
    c = _conn(tmp_path)
    apply_schema(c, enable_vec=True)
    cols = {r[1] for r in c.execute('PRAGMA table_info(memory_entries)')}
    assert NEW_COLS <= cols
    c.close()


def test_migration_from_v9_adds_columns(tmp_path):
    # minimal v9-shaped memory_entries WITHOUT the new columns, version pinned to 9
    db = str(tmp_path / 'v9.db')
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE db_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO db_metadata VALUES ('schema_version','9','2026-01-01T00:00:00+00:00');
        CREATE TABLE agent_sessions (session_id TEXT PRIMARY KEY, agent_name TEXT NOT NULL,
            public_key TEXT NOT NULL, parent_session_id TEXT, created_at TEXT NOT NULL, metadata TEXT);
        CREATE TABLE memory_entries (entry_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
            entry_type TEXT NOT NULL, content TEXT NOT NULL, session_id TEXT NOT NULL,
            sequence_num INTEGER NOT NULL, signature TEXT NOT NULL, created_at TEXT NOT NULL,
            reasoning_chain_id TEXT, importance REAL NOT NULL DEFAULT 0.5, metadata TEXT);
        INSERT INTO memory_entries (entry_id,content_hash,entry_type,content,session_id,
            sequence_num,signature,created_at,importance,metadata)
            VALUES ('e1','ch','observation','{}','s1',1,'sig','2026-01-01',0.5,'{}');
    """)
    c.commit()
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    apply_schema(c, enable_vec=False)
    assert get_schema_version(c) == 10
    cols = {r[1] for r in c.execute('PRAGMA table_info(memory_entries)')}
    assert NEW_COLS <= cols
    # the pre-existing row survives migration
    assert c.execute("SELECT status FROM memory_entries WHERE entry_id='e1'").fetchone()[0] == 'pending'
    c.close()


def test_migration_is_idempotent(tmp_path):
    c = _conn(tmp_path)
    apply_schema(c, enable_vec=True)
    apply_schema(c, enable_vec=True)
    assert get_schema_version(c) == 10
    c.close()


def test_status_check_rejects_unknown_value(tmp_path):
    c = _conn(tmp_path)
    apply_schema(c, enable_vec=True)
    c.execute('PRAGMA foreign_keys=OFF')
    c.execute("INSERT INTO agent_sessions (session_id,agent_name,public_key,created_at) "
              "VALUES ('s1','t','pk','2026-01-01')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO memory_entries (entry_id,content_hash,entry_type,content,"
                  "session_id,sequence_num,signature,created_at,importance,status) "
                  "VALUES ('e1','ch','observation','{}','s1',1,'sig','2026-01-01',0.5,'bogus')")
    c.close()


def test_status_defaults_to_pending(tmp_path):
    c = _conn(tmp_path)
    apply_schema(c, enable_vec=True)
    c.execute("INSERT INTO agent_sessions (session_id,agent_name,public_key,created_at) "
              "VALUES ('s1','t','pk','2026-01-01')")
    c.execute("INSERT INTO memory_entries (entry_id,content_hash,entry_type,content,session_id,"
              "sequence_num,signature,created_at,importance) "
              "VALUES ('e1','ch','observation','{}','s1',1,'sig','2026-01-01',0.5)")
    assert c.execute("SELECT status FROM memory_entries WHERE entry_id='e1'").fetchone()[0] == 'pending'
    c.close()


def test_v10_indexes_exist(tmp_path):
    c = _conn(tmp_path)
    apply_schema(c, enable_vec=True)
    names = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}
    for idx in ['idx_entries_status', 'idx_entries_trust_score', 'idx_entries_kind',
                'idx_entries_source', 'idx_entries_domain', 'idx_entries_valid_to',
                'idx_entries_pinned']:
        assert idx in names, f'missing {idx}'
    c.close()
