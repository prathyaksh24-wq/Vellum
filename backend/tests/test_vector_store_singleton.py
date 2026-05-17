"""Verify get_vector_store() returns a single shared VectorStore.

Local-mode Qdrant rejects a second client on the same storage path. Before
this fix the watcher (via VaultIngester(), which called VectorStore()
directly) would race with the chat path's client and crash flush threads."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.rag import store as store_mod


@pytest.fixture(autouse=True)
def _reset_singleton():
    store_mod.reset_vector_store_for_tests()
    yield
    store_mod.reset_vector_store_for_tests()


def test_get_vector_store_returns_same_instance() -> None:
    sentinel = object()
    with patch.object(store_mod, "VectorStore", return_value=sentinel) as ctor:
        a = store_mod.get_vector_store()
        b = store_mod.get_vector_store()
        c = store_mod.get_vector_store()
    assert a is b is c is sentinel
    assert ctor.call_count == 1  # constructed exactly once


def test_singleton_resets_for_tests() -> None:
    first = object()
    second = object()
    with patch.object(store_mod, "VectorStore", side_effect=[first, second]) as ctor:
        a = store_mod.get_vector_store()
        store_mod.reset_vector_store_for_tests()
        b = store_mod.get_vector_store()
    assert a is first
    assert b is second
    assert ctor.call_count == 2


def test_ingester_default_uses_singleton() -> None:
    """Verify VaultIngester picks up the shared store by default."""
    from agent.obsidian import ingester as ingester_mod

    sentinel = object()
    with patch.object(store_mod, "VectorStore", return_value=sentinel):
        # Bypass Embedder/scrubber heavy init by patching them.
        with patch.object(ingester_mod, "Embedder") as embedder_mock, \
             patch.object(ingester_mod, "PrivacyScrubber") as scrub_mock, \
             patch.object(ingester_mod, "get_settings") as settings_mock:
            settings_mock.return_value.obsidian_vault_path = "."
            embedder_mock.return_value = object()
            scrub_mock.return_value = object()
            ing = ingester_mod.VaultIngester()
            assert ing.store is sentinel
