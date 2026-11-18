"""The embedding model an install uses: chosen once, pinned, and never silently changed."""
import json
from pathlib import Path

import pytest

from agent.config import Settings
from agent.rag import embedding_profile as ep


def _fresh_settings(monkeypatch, **explicit):
    for name in ("EMBEDDING_BACKEND", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS",
                 "EMBEDDING_MODEL_REVISION", "CHROMA_PATH"):
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None, **explicit)


def test_no_ollama_pins_the_bundled_model(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_ollama_has", lambda *_: False)
    assert ep.ensure_profile(tmp_path, "http://127.0.0.1:11434") == ep.BUNDLED
    assert json.loads(ep.profile_path(tmp_path).read_text())["profile"] == ep.BUNDLED


def test_ollama_with_embeddinggemma_keeps_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_ollama_has", lambda *_: True)
    assert ep.ensure_profile(tmp_path, "http://127.0.0.1:11434") == ep.OLLAMA


def test_existing_embeddinggemma_index_is_never_stranded(tmp_path, monkeypatch):
    # Ollama happens to be down on first launch after the update: keep the existing index.
    (tmp_path / ep.PROFILES[ep.OLLAMA]["chroma_path"]).mkdir(parents=True)
    monkeypatch.setattr(ep, "_ollama_has", lambda *_: False)
    assert ep.ensure_profile(tmp_path, "http://127.0.0.1:11434") == ep.OLLAMA


def test_pin_survives_later_installing_ollama(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_ollama_has", lambda *_: False)
    ep.ensure_profile(tmp_path, "")
    monkeypatch.setattr(ep, "_ollama_has", lambda *_: True)
    assert ep.ensure_profile(tmp_path, "") == ep.BUNDLED


def test_apply_pinned_sets_model_dimensions_and_its_own_index(tmp_path, monkeypatch):
    ep.profile_path(tmp_path).parent.mkdir(parents=True)
    ep.profile_path(tmp_path).write_text(json.dumps({"profile": ep.BUNDLED}))
    settings = _fresh_settings(monkeypatch)
    ep.apply_pinned(settings, tmp_path)
    bundled = ep.PROFILES[ep.BUNDLED]
    assert (settings.embedding_backend, settings.embedding_model, settings.embedding_dimensions) == (
        "llama_server", bundled["embedding_model"], bundled["embedding_dimensions"])
    assert settings.chroma_path == (tmp_path / bundled["chroma_path"]).resolve()


def test_explicit_embedding_settings_win(tmp_path, monkeypatch):
    ep.profile_path(tmp_path).parent.mkdir(parents=True)
    ep.profile_path(tmp_path).write_text(json.dumps({"profile": ep.BUNDLED}))
    settings = _fresh_settings(monkeypatch, EMBEDDING_BACKEND="ollama", EMBEDDING_MODEL="embeddinggemma-2:270m-q8_0-text")
    ep.apply_pinned(settings, tmp_path)
    assert settings.embedding_backend == "ollama"
    assert settings.embedding_dimensions == 768


def test_unknown_or_corrupt_pin_is_ignored(tmp_path, monkeypatch):
    ep.profile_path(tmp_path).parent.mkdir(parents=True)
    ep.profile_path(tmp_path).write_text("{not json")
    assert ep.read_pin(tmp_path) == ""
    ep.profile_path(tmp_path).write_text(json.dumps({"profile": "something-else"}))
    settings = _fresh_settings(monkeypatch)
    ep.apply_pinned(settings, tmp_path)
    assert settings.embedding_backend == "ollama"


def test_bundled_embedder_uses_gemma_prefixes_and_its_own_fingerprint(monkeypatch):
    from agent.rag import embedding_server
    from agent.rag.embedder import DOCUMENT_PREFIX, QUERY_PREFIX, Embedder

    sent = []

    class Response:
        def __init__(self, inputs):
            self._inputs = inputs

        def raise_for_status(self):
            return None

        def json(self):
            # Out of order on purpose: results are matched by index.
            return {"data": [{"index": i, "embedding": [1.0] + [0.0] * 767} for i in reversed(range(len(self._inputs)))]}

    def fake_post(url, json, **_):
        sent.append((url, json["input"]))
        return Response(json["input"])

    class FakeServer:
        def url(self):
            return "http://127.0.0.1:5"

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(embedding_server, "get_embedding_server", lambda: FakeServer())
    bundled = ep.PROFILES[ep.BUNDLED]
    embedder = Embedder(bundled["embedding_model"])
    assert embedder.backend == "llama_server" and embedder.dimensions == 768
    embedder.embed_query("what food?")
    embedder.embed_batch(["The user is vegan.", "second"])
    assert sent == [("http://127.0.0.1:5/v1/embeddings", [QUERY_PREFIX + "what food?"]),
                    ("http://127.0.0.1:5/v1/embeddings", [DOCUMENT_PREFIX + "The user is vegan.",
                                                          DOCUMENT_PREFIX + "second"])]
    assert embedder.revision == bundled["embedding_model_revision"] + ":retrieval-prefix-v1"
    ollama = Embedder(ep.PROFILES[ep.OLLAMA]["embedding_model"])
    assert embedder.fingerprint != ollama.fingerprint  # never mixed into the Ollama index


def test_bundled_embedder_rejects_wrong_dimensions(monkeypatch):
    from agent.rag import embedding_server
    from agent.rag.embedder import Embedder

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [1.0] * 384}]}

    class FakeServer:
        def url(self):
            return "http://127.0.0.1:5"

    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())
    monkeypatch.setattr(embedding_server, "get_embedding_server", lambda: FakeServer())
    with pytest.raises(ValueError, match="dimensions"):
        Embedder(ep.PROFILES[ep.BUNDLED]["embedding_model"]).embed_query("x")


def test_embedding_server_restarts_after_idle_stop(tmp_path, monkeypatch):
    from agent.rag import embedding_server as es

    launched = []

    class Proc:
        def __init__(self, argv, **_):
            launched.append(argv)
            self.pid, self.returncode, self.alive = 1000 + len(launched), None, True

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.alive = False

    monkeypatch.setattr(es.subprocess, "Popen", Proc)
    monkeypatch.setattr(es, "_healthy", lambda url: True)
    server = es.EmbeddingServer(tmp_path / "llama-server.exe", tmp_path / "model.gguf", idle_seconds=3600)
    monkeypatch.setattr(server, "_attach_job", lambda pid: None)
    monkeypatch.setattr(server, "_ensure_reaper", lambda: None)
    first = server.url()
    assert first.startswith("http://127.0.0.1:") and server.url() == first and len(launched) == 1
    argv = launched[0]
    assert "--embeddings" in argv and argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("-m") + 1] == str(tmp_path / "model.gguf")
    server.stop()  # what the idle reaper does
    server.url()
    assert len(launched) == 2


@pytest.mark.skipif(ep.bundled_model_path(Path(__file__).resolve().parents[2]) is None,
                    reason="bundled model not prepared (setup_memory_engines.py embedding-model)")
def test_bundled_embeddinggemma_runs_without_ollama_and_ranks_memories(monkeypatch):
    from agent.rag import embedding_server
    from agent.rag.embedder import Embedder

    monkeypatch.setattr(embedding_server, "_server", None)
    embedder = Embedder(ep.PROFILES[ep.BUNDLED]["embedding_model"])
    try:
        docs = embedder.embed_batch(["The user is vegan and avoids animal products.",
                                     "The user practices Japanese every evening."])
        assert len(docs[0]) == 768
        query = embedder.embed_query("which language is the user learning?")
        scores = [sum(a * b for a, b in zip(query, doc)) for doc in docs]
        assert scores[1] > scores[0]
    finally:
        if embedding_server._server is not None:
            embedding_server._server.stop()


def test_explicit_chroma_path_is_kept(tmp_path, monkeypatch):
    ep.profile_path(tmp_path).parent.mkdir(parents=True)
    ep.profile_path(tmp_path).write_text(json.dumps({"profile": ep.BUNDLED}))
    settings = _fresh_settings(monkeypatch, CHROMA_PATH=str(tmp_path / "my-index"))
    ep.apply_pinned(settings, tmp_path)
    assert settings.chroma_path == tmp_path / "my-index"
