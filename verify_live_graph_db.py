"""
Live verification of the deployed hard-isolation code against the REAL HA graph.db.

Usage:
    python3 verify_live_graph_db.py <path-to-live-graph.db-copy>

It loads the EXACT graph_store.py that was deployed to HA, opens a COPY of the
live graph.db (never touches the live file), and asserts:
  1. nodes / edges tables both carry the `user` column (schema created/migrated)
  2. cross-user recall isolation holds on real data
  3. user=None sees ONLY the public (NULL) layer
  4. include_all=True sees everything (system / cleanup scope)
"""
import sys
import importlib.util
import sqlite3
import tempfile
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent
GS_PATH = REPO / "custom_components/claw_assistant/runtime/storage/graph_store.py"

_spec = importlib.util.spec_from_file_location("gs_live", GS_PATH)
gs = importlib.util.module_from_spec(_spec)
sys.modules["gs_live"] = gs
_spec.loader.exec_module(gs)
GraphStore = gs.GraphStore


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: verify_live_graph_db.py <live-graph.db>")
        return 2

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"[WARN] {src} does not exist yet -> testing fresh schema creation only")
        tmp = Path(tempfile.mkdtemp()) / "fresh_graph.db"
    else:
        tmp = Path(tempfile.mkdtemp()) / "graph_test.db"
        shutil.copy(src, tmp)
        print(f"[INFO] copied live db ({src.stat().st_size} bytes) -> {tmp}")

    store = GraphStore(str(tmp))

    # 1) schema check
    ncols = {r[1] for r in store._conn.execute("PRAGMA table_info(nodes)").fetchall()}
    ecols = {r[1] for r in store._conn.execute("PRAGMA table_info(edges)").fetchall()}
    assert "user" in ncols, "FAIL: nodes.user missing"
    assert "user" in ecols, "FAIL: edges.user missing"
    print("[OK] schema: nodes.user + edges.user present on REAL db")

    # 2) existing node user distribution (bonus visibility)
    try:
        dist = [
            (r[0], r[1])
            for r in store._conn.execute(
                "SELECT user, COUNT(*) FROM nodes GROUP BY user"
            ).fetchall()
        ]
        print(f"[INFO] existing node user distribution: {dist}")
    except sqlite3.OperationalError:
        print("[INFO] no nodes yet (fresh db)")

    # 3) cross-user isolation on real db
    store.upsert_node(kind="fact", title="A secret note", body="secret", user="user_A")
    store.upsert_node(kind="fact", title="B secret note", body="secret", user="user_B")
    store.upsert_node(kind="rule", title="public family rule", body="secret", user=None)

    hits_a = {h.node.title for h in store.recall("secret", user="user_A")}
    hits_b = {h.node.title for h in store.recall("secret", user="user_B")}
    hits_none = {h.node.title for h in store.recall("secret", user=None)}
    hits_all = {h.node.title for h in store.recall("secret", include_all=True)}

    assert "A secret note" in hits_a and "B secret note" not in hits_a, f"A leak: {hits_a}"
    assert "B secret note" in hits_b and "A secret note" not in hits_b, f"B leak: {hits_b}"
    assert (
        "A secret note" not in hits_none and "B secret note" not in hits_none
    ), f"None leak: {hits_none}"
    assert (
        "A secret note" in hits_all and "B secret note" in hits_all
    ), f"All miss: {hits_all}"

    print("[OK] cross-user isolation verified on REAL db")
    print(f"  user_A sees: {sorted(hits_a)}")
    print(f"  user_B sees: {sorted(hits_b)}")
    print(f"  None   sees: {sorted(hits_none)}")
    print(f"  All    sees: {sorted(hits_all)}")

    store.close()
    print("LIVE_VERIFY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
