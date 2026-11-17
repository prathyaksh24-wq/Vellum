"""Verify get_vector_store() returns a single shared VectorStore.

Embedded Chroma should be opened through one process-wide client for a path.
The watcher and chat path share this singleton instead of racing separate
clients against the same storage directory."""

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
