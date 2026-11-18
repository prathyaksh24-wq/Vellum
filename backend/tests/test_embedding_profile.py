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
        "sentence_transformers", bundled["embedding_model"], bundled["embedding_dimensions"])
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


def test_bundled_embedder_adds_e5_prefixes_and_its_own_fingerprint(monkeypatch):
    from agent.rag.embedder import Embedder

    class Recorder:
        seen: list = []

        def encode(self, texts, **_):
            self.seen.append(texts)
            import numpy as np
            return np.ones((len(texts), 384)) if isinstance(texts, list) else np.ones(384)

    bundled = ep.PROFILES[ep.BUNDLED]
    embedder = Embedder(bundled["embedding_model"])
    embedder.dimensions, embedder.model_revision = bundled["embedding_dimensions"], bundled["embedding_model_revision"]
    embedder.__dict__["model"] = Recorder()
    embedder.embed_query("what food?")
    embedder.embed_batch(["The user is vegan."])
    embedder.embed("legacy document")
    assert Recorder.seen == [["query: what food?"], ["passage: The user is vegan."], "passage: legacy document"]
    assert embedder.bundled and embedder.revision.endswith(":retrieval-prefix-v1")


def test_other_sentence_transformer_models_get_no_prefix():
    from agent.rag.embedder import Embedder

    embedder = Embedder("BAAI/bge-m3")
    assert not embedder.bundled
    assert embedder._prefixed(["x"], query=True) == ["x"]


@pytest.mark.skipif(ep.bundled_model_path(Path(__file__).resolve().parents[2]) is None,
                    reason="bundled model not prepared (setup_memory_engines.py embedding-model)")
def test_bundled_model_loads_from_disk_and_ranks_memories(monkeypatch):
    from agent.rag.embedder import Embedder

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # must never download
    bundled = ep.PROFILES[ep.BUNDLED]
    embedder = Embedder(bundled["embedding_model"])
    docs = embedder.embed_batch(["The user is vegan and avoids animal products.",
                                 "The user practices Japanese every evening."])
    assert len(docs[0]) == bundled["embedding_dimensions"]
    query = embedder.embed_query("which language is the user learning?")
    scores = [sum(a * b for a, b in zip(query, doc)) for doc in docs]
    assert scores[1] > scores[0]


def test_explicit_chroma_path_is_kept(tmp_path, monkeypatch):
    ep.profile_path(tmp_path).parent.mkdir(parents=True)
    ep.profile_path(tmp_path).write_text(json.dumps({"profile": ep.BUNDLED}))
    settings = _fresh_settings(monkeypatch, CHROMA_PATH=str(tmp_path / "my-index"))
    ep.apply_pinned(settings, tmp_path)
    assert settings.chroma_path == tmp_path / "my-index"
