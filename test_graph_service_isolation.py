"""Local QA: verify user_key propagation graph_service -> graph_store.

The HA runtime is unavailable locally, so we stub the `homeassistant` package
and inject a GraphStore singleton directly. This covers T3 (graph_service
passthrough) and the P0/P1/P2 hardening without a full HA stack.

What this proves:
  * recall_memory_lines_sync() only surfaces the requesting user's nodes + the
    public (NULL) layer -- the P0 leak is closed.
  * async_remember(user=None) funnels an unidentified session into the
    "anonymous" sentinel instead of the NULL public layer -- P1 holds.
  * async_recall(user=...) reaches graph_store.recall(user=...) unchanged.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parent
_GS_PATH = _ROOT / "custom_components/claw_assistant/runtime/storage/graph_store.py"
_GSE_PATH = _ROOT / "custom_components/claw_assistant/runtime/storage/graph_service.py"
_MD_PATH = _ROOT / "custom_components/claw_assistant/runtime/storage/md_to_graph.py"


def _load_modules():
    mod_name = "claw_assistant.runtime.storage.graph_service"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    # Stub the heavy HA runtime so module-top imports succeed.
    sys.modules.setdefault("homeassistant", mock.MagicMock())
    sys.modules.setdefault("homeassistant.core", mock.MagicMock())
    sys.modules.setdefault("homeassistant.helpers", mock.MagicMock())

    # Package placeholders so relative imports resolve without executing the
    # real __init__.py chains (which would pull in all of HA).
    for name in [
        "claw_assistant",
        "claw_assistant.runtime",
        "claw_assistant.runtime.storage",
        "claw_assistant.runtime.utils",
    ]:
        sys.modules.setdefault(name, types.ModuleType(name))

    # graph_service imports get_data_dir but never calls it in our tests.
    data_path_stub = types.ModuleType("claw_assistant.runtime.utils.data_path")
    data_path_stub.get_data_dir = lambda: Path("/tmp")
    sys.modules["claw_assistant.runtime.utils.data_path"] = data_path_stub

    def _load(path, fullname):
        spec = importlib.util.spec_from_file_location(fullname, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = mod
        spec.loader.exec_module(mod)
        return mod

    _load(_GS_PATH, "claw_assistant.runtime.storage.graph_store")
    _load(_MD_PATH, "claw_assistant.runtime.storage.md_to_graph")
    return _load(_GSE_PATH, mod_name)


@pytest.fixture
def graph_service():
    return _load_modules()


@pytest.fixture
def store(graph_service):
    import tempfile

    GraphStore = graph_service.GraphStore
    with tempfile.TemporaryDirectory() as tmp:
        s = GraphStore(Path(tmp) / "g.db")
        yield s
        s.close()


def _fake_hass(store, graph_service):
    """Minimal HA hass stub whose executor job runs synchronously."""
    hass = mock.MagicMock()
    hass.data = {graph_service._HASS_DATA_KEY: store}

    async def _run(func, *args):
        return func(*args)

    hass.async_add_executor_job = _run
    return hass


def test_recall_memory_lines_sync_isolates_users(graph_service, store):
    graph_service._singleton_store = store
    store.upsert_node(kind="fact", title="A drinks tea", body="preference", user="user_A")
    store.upsert_node(kind="fact", title="B drinks coffee", body="preference", user="user_B")
    # Public node must also match the query term to prove it is *visible* to A.
    store.upsert_node(kind="rule", title="family drinks water", body="rule", user=None)

    lines_a = graph_service.recall_memory_lines_sync("drinks", user="user_A")
    text_a = " ".join(lines_a)
    assert "A drinks tea" in text_a
    assert "family drinks water" in text_a
    assert "B drinks coffee" not in text_a

    lines_b = graph_service.recall_memory_lines_sync("drinks", user="user_B")
    text_b = " ".join(lines_b)
    assert "B drinks coffee" in text_b
    assert "A drinks tea" not in text_b


def test_recall_memory_lines_sync_unidentified_sees_only_public(graph_service, store):
    graph_service._singleton_store = store
    store.upsert_node(kind="fact", title="A private", body="x", user="user_A")
    store.upsert_node(kind="rule", title="family rule", body="y", user=None)

    # user=None means "unidentified viewer" -> public layer only (P0 fix).
    lines = graph_service.recall_memory_lines_sync("x y", user=None)
    text = " ".join(lines)
    assert "family rule" in text
    assert "A private" not in text


def test_async_remember_unidentified_uses_sentinel(graph_service, store):
    hass = _fake_hass(store, graph_service)

    async def _go():
        return await graph_service.async_remember(
            hass, kind="fact", title="secret", body="x", user=None
        )

    result = asyncio.run(_go())
    assert result is not None
    node_id, _ = result
    node = store.get(node_id)
    assert node.user == graph_service.ANONYMOUS_USER_KEY  # "anonymous"


def test_async_remember_identified_keeps_user(graph_service, store):
    hass = _fake_hass(store, graph_service)

    async def _go():
        return await graph_service.async_remember(
            hass, kind="fact", title="mine", body="z", user="user_A"
        )

    result = asyncio.run(_go())
    node = store.get(result[0])
    assert node.user == "user_A"


def test_async_recall_respects_user(graph_service, store):
    hass = _fake_hass(store, graph_service)
    store.upsert_node(kind="fact", title="A node", body="alpha", user="user_A")
    store.upsert_node(kind="fact", title="B node", body="beta", user="user_B")

    async def _go():
        return await graph_service.async_recall(hass, "node", user="user_A")

    hits = asyncio.run(_go())
    titles = {h.node.title for h in hits}
    assert "A node" in titles
    assert "B node" not in titles
