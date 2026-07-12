"""Unit tests for per-user (hard) isolation in GraphStore.

GraphStore is pure stdlib (no HomeAssistant dependency), so it can be exercised
standalone. These tests prove that long-term graph memory is isolated per
``user_key`` while still sharing a family-public layer (``user IS NULL``).
"""

import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent
_GS_PATH = (
    _REPO
    / "custom_components"
    / "claw_assistant"
    / "runtime"
    / "storage"
    / "graph_store.py"
)

_spec = importlib.util.spec_from_file_location("gs_iso_test", _GS_PATH)
_graph_store = importlib.util.module_from_spec(_spec)
import sys as _sys

_sys.modules["gs_iso_test"] = _graph_store
_spec.loader.exec_module(_graph_store)
GraphStore = _graph_store.GraphStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "graph.db"
        s = GraphStore(db)
        try:
            yield s
        finally:
            s.close()


def test_user_column_added_on_fresh_db(store):
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(nodes)").fetchall()}
    assert "user" in cols


def test_migration_adds_user_column_to_legacy_db():
    """A pre-existing DB without the user column must be migrated safely."""
    tmp = tempfile.mkdtemp()
    try:
        db = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(
            """
            CREATE TABLE nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                checksum TEXT NOT NULL UNIQUE,
                source_doc TEXT,
                created_at REAL NOT NULL,
                last_accessed_at REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 1,
                confidence REAL NOT NULL DEFAULT 1.0,
                pinned INTEGER NOT NULL DEFAULT 0,
                embedding BLOB
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                title, body, node_id UNINDEXED, tokenize='unicode61'
            );
            """
        )
        conn.commit()
        conn.close()

        s = GraphStore(db)  # should migrate without error
        try:
            cols = {
                r[1] for r in s._conn.execute("PRAGMA table_info(nodes)").fetchall()
            }
            assert "user" in cols
            # legacy rows keep user = NULL (public)
            nid, _ = s.upsert_node(kind="fact", title="legacy fact", body="x")
            node = s.get(nid)
            assert node.user is None
        finally:
            s.close()
    finally:
        for attempt in range(5):
            try:
                for p in Path(tmp).glob("*"):
                    p.unlink()
                Path(tmp).rmdir()
                break
            except OSError:
                import time as _t

                _t.sleep(0.2)


def test_recall_isolation_between_users(store):
    # Public node must also match the query tokens to be surfaced.
    store.upsert_node(kind="preference", title="likes tea", body="drinks", user="user_A")
    store.upsert_node(kind="preference", title="likes coffee", body="drinks", user="user_B")
    store.upsert_node(kind="rule", title="family quiet hours", body="drinks rules", user=None)

    hits_a = {h.node.title for h in store.recall("likes drinks", user="user_A")}
    hits_b = {h.node.title for h in store.recall("likes drinks", user="user_B")}

    assert "likes tea" in hits_a
    assert "family quiet hours" in hits_a  # public layer visible to everyone
    assert "likes coffee" not in hits_a

    assert "likes coffee" in hits_b
    assert "family quiet hours" in hits_b
    assert "likes tea" not in hits_b

    # user=None (unidentified viewer) sees ONLY the public layer, never
    # another user's private memory.
    hits_public = {h.node.title for h in store.recall("likes drinks", user=None)}
    assert hits_public == {"family quiet hours"}

    # include_all is the explicit global/admin view.
    hits_all = {h.node.title for h in store.recall("likes drinks", include_all=True)}
    assert hits_all == {"likes tea", "likes coffee", "family quiet hours"}


def test_upsert_stores_user(store):
    nid, _ = store.upsert_node(kind="fact", title="t", body="b", user="user_X")
    assert store.get(nid).user == "user_X"
    # default is public
    nid2, _ = store.upsert_node(kind="fact", title="t2", body="b2")
    assert store.get(nid2).user is None


def test_checksum_per_user_no_collision(store):
    # Same content, two different users -> two distinct nodes.
    _, new_a = store.upsert_node(kind="fact", title="same", body="same", user="user_A")
    _, new_b = store.upsert_node(kind="fact", title="same", body="same", user="user_B")
    assert new_a is True
    assert new_b is True
    stats = store.stats()
    assert stats["nodes"] == 2

    # Same user again -> update, not a new node.
    _, new_a2 = store.upsert_node(kind="fact", title="same", body="same", user="user_A")
    assert new_a2 is False
    assert store.stats()["nodes"] == 2


def test_expand_respects_user(store):
    a_id, _ = store.upsert_node(kind="fact", title="alice secret", body="x", user="user_A")
    b_id, _ = store.upsert_node(kind="fact", title="bob secret", body="x", user="user_B")
    store.link(a_id, b_id, "related_to")

    # user_B recalling bob must NOT surface alice via the edge.
    hits = store.recall("secret", user="user_B", expand=True)
    titles = {h.node.title for h in hits}
    assert "bob secret" in titles
    assert "alice secret" not in titles

    # include_all sees both (admin / global view).
    hits_all = store.recall("secret", include_all=True, expand=True)
    titles_all = {h.node.title for h in hits_all}
    assert "alice secret" in titles_all
    assert "bob secret" in titles_all


def test_recall_none_is_public_only(store):
    store.upsert_node(kind="fact", title="only A", body="x", user="user_A")
    store.upsert_node(kind="fact", title="only B", body="x", user="user_B")
    store.upsert_node(kind="fact", title="public fact", body="x", user=None)
    # An unidentified viewer sees ONLY the public layer.
    hits = store.recall("fact", user=None)
    titles = {h.node.title for h in hits}
    assert titles == {"public fact"}


def test_recall_include_all_global(store):
    store.upsert_node(kind="fact", title="only A", body="x", user="user_A")
    store.upsert_node(kind="fact", title="only B", body="x", user="user_B")
    # include_all is the explicit global view used by maintenance tasks.
    hits = store.recall("only", include_all=True)
    titles = {h.node.title for h in hits}
    assert titles == {"only A", "only B"}


def test_anonymous_key_is_private(store):
    sentinel = _graph_store.ANONYMOUS_USER_KEY
    assert sentinel

    nid, _ = store.upsert_node(kind="fact", title="mystery", body="x", user=sentinel)
    # Not visible to an unidentified (public-only) viewer.
    public_hits = {h.node.title for h in store.recall("mystery", user=None)}
    assert "mystery" not in public_hits
    # Visible to the anonymous identity itself.
    anon_hits = {h.node.title for h in store.recall("mystery", user=sentinel)}
    assert "mystery" in anon_hits
    # Anonymous memory does NOT leak into the family public layer.
    assert store.get(nid).user == sentinel


def test_edge_carries_user_and_is_scoped(store):
    a_id, _ = store.upsert_node(kind="fact", title="alice", body="x", user="user_A")
    b_id, _ = store.upsert_node(kind="fact", title="bob", body="x", user="user_B")
    store.link(a_id, b_id, "related_to", user="user_A")

    edge_user = store._conn.execute(
        "SELECT user FROM edges WHERE src_id=? AND dst_id=?", (a_id, b_id)
    ).fetchone()["user"]
    assert edge_user == "user_A"

    # neighbours() honours the user scope on edges.
    assert len(store.neighbors(a_id, user="user_A")) == 1
    assert len(store.neighbors(a_id, user="user_B")) == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
