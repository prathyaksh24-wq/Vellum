"""Which embedding model this install uses, decided once and then pinned.

Every install uses Google's EmbeddingGemma 2 (Q8_0, 768 dimensions):

- Through Ollama when Ollama already has ``embeddinggemma-2:270m-q8_0-text``
  (or an index built with it exists).
- Otherwise through the copy bundled with Vellum, run by llama.cpp's
  ``llama-server`` (agent/rag/embedding_server.py): no Ollama, no download at
  runtime, nothing sent to a cloud provider just to index memories. Claude and
  Groq have no embedding API, and following the chat provider would force
  re-indexing every memory whenever the user switched model.

Both are the same model; their vectors agree to a cosine of 0.9998 or
better. Each still keeps its own index, so an install never mixes vectors
from two runtimes. The choice is written to ``data/embeddings/profile.json``
the first time the desktop backend starts (``ensure_profile``) and applied by
``get_settings`` from then on. Explicit ``EMBEDDING_*`` / ``CHROMA_PATH``
settings always win.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

OLLAMA = "ollama-embeddinggemma"
BUNDLED = "bundled"

PROFILES: dict[str, dict[str, Any]] = {
    OLLAMA: {
        "embedding_backend": "ollama",
        "embedding_model": "embeddinggemma-2:270m-q8_0-text",
        "embedding_dimensions": 768,
        "embedding_model_revision": "c21dd30c1e38444d3b4faa091407b6fa97221447b4965d74931d43d7f09bbbfd",
        "chroma_path": "data/embeddings/chroma-embeddinggemma2-v1",
    },
    BUNDLED: {
        # ggml-org's official GGUF of google/embeddinggemma-2 (Apache 2.0); the
        # revision is the file's sha256.
        "embedding_backend": "llama_server",
        "embedding_model": "embeddinggemma-2-Q8_0.gguf",
        "embedding_dimensions": 768,
        "embedding_model_revision": "2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135",
        "chroma_path": "data/embeddings/chroma-embeddinggemma2-bundled-v1",
    },
}
# Bundled model folder: <resources>/engine-runtimes/embedding-models/<dir> when
# packaged, .engines/embedding-models/<dir> in development.
BUNDLED_DIR = "embeddinggemma-2"


def profile_path(root: Path) -> Path:
    return Path(root) / "data" / "embeddings" / "profile.json"


def read_pin(root: Path) -> str:
    try:
        name = json.loads(profile_path(root).read_text(encoding="utf-8")).get("profile", "")
    except (OSError, ValueError):
        return ""
    return name if name in PROFILES else ""


def apply_pinned(settings: Any, root: Path) -> None:
    """Apply the pinned profile to fields the user didn't set explicitly. No I/O beyond one file read."""
    name = read_pin(root)
    if not name:
        return
    explicit = getattr(settings, "model_fields_set", set())
    if {"embedding_backend", "embedding_model"} & explicit:
        return  # the user chose an embedding model themselves
    profile = PROFILES[name]
    for field in ("embedding_backend", "embedding_model", "embedding_dimensions", "embedding_model_revision"):
        object.__setattr__(settings, field, profile[field])
    # Settings resolves chroma_path after validation, which marks it as set, so
    # "explicit" here means it differs from the default index folder.
    from agent.config import Settings, _resolve_against_repo

    default_index = _resolve_against_repo(Settings.model_fields["chroma_path"].default)
    if settings.chroma_path is not None and Path(settings.chroma_path) == default_index:
        object.__setattr__(settings, "chroma_path", (Path(root) / profile["chroma_path"]).resolve())


def _ollama_has(base_url: str, model: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=1.5) as response:  # noqa: S310 - loopback
            tags = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return any(item.get("name") == model for item in tags.get("models", []))


def choose(root: Path, ollama_base_url: str) -> str:
    """Pick a profile for a fresh install. Existing EmbeddingGemma data always stays on it."""
    if (Path(root) / PROFILES[OLLAMA]["chroma_path"]).exists():
        return OLLAMA  # never strand an existing index because Ollama happened to be down
    if _ollama_has(ollama_base_url, PROFILES[OLLAMA]["embedding_model"]):
        return OLLAMA
    return BUNDLED


def ensure_profile(root: Path, ollama_base_url: str) -> str:
    """Pin the profile on first run (desktop backend startup). Returns the pinned name."""
    existing = read_pin(root)
    if existing:
        return existing
    name = choose(root, ollama_base_url)
    path = profile_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"profile": name}), encoding="utf-8")
    return name


def bundled_model_path(root: Path) -> Path | None:
    """The bundled GGUF: packaged app first, then development."""
    import sys

    resources = Path(sys.executable).resolve().parents[2]
    name = PROFILES[BUNDLED]["embedding_model"]
    for folder in (resources / "engine-runtimes" / "embedding-models" / BUNDLED_DIR,
                   Path(root) / ".engines" / "embedding-models" / BUNDLED_DIR):
        if (folder / name).is_file():
            return folder / name
    return None
