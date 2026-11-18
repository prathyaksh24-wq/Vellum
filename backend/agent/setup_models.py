"""Recommend local models from Hugging Face, sized to this computer.

Ollama can run any GGUF on Hugging Face directly (``hf.co/<repo>:<quant>``),
so onboarding can offer more than a fixed list: official releases,
fine-tunes, coding models, and (only when the user opts in) uncensored
variants. For each repo this picks the highest-quality quantization that
fits the machine's GPU memory, or system RAM when there is no suitable GPU.

Only public model metadata is fetched from huggingface.co; nothing about the
user is sent. Search ranking alone is not trusted: the most-downloaded
match for a popular model can be an uncensored fine-tune, so every result
is classified and uncensored ones are hidden unless asked for.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

HF_API = "https://huggingface.co/api"
# Quantizations best quality first. A model needs its file size plus
# headroom for the context cache and runtime.
QUANT_ORDER = ("Q8_0", "Q6_K", "Q5_K_M", "Q5_K_S", "Q4_K_M", "Q4_K_S", "IQ4_XS", "IQ4_NL",
               "Q3_K_L", "Q3_K_M", "IQ3_M", "Q3_K_S", "Q2_K", "IQ2_M")
HEADROOM = 1.2
LOW_QUANTS = {"Q3_K_L", "Q3_K_M", "IQ3_M", "Q3_K_S", "Q2_K", "IQ2_M"}  # noticeably lossy
_QUANT_RE = re.compile(r"(?:^|[-_.])(IQ\d_[A-Z]+|Q\d_K_[SML]|Q\d_K|Q\d_0)(?=[-_.]|\.gguf$)", re.IGNORECASE)
_UNCENSORED_RE = re.compile(r"uncensor|abliterat|heretic|uncnr|\bnsfw\b|unfiltered|lewd", re.IGNORECASE)
TRUSTED_UPLOADERS = ("unsloth", "bartowski", "lmstudio-community", "ggml-org", "Qwen", "google",
                     "microsoft", "mistralai", "meta-llama", "deepseek-ai", "ibm-granite")
CURATED_QUERIES = {
    "general": ("qwen3.5 9b", "gemma-4 12b", "llama 3.1 8b instruct"),
    "coding": ("qwen2.5 coder 7b", "deepseek coder"),
    "small": ("gemma-4 4b", "phi-4 mini", "qwen3.5 4b"),
}


@dataclass
class ModelOption:
    repo: str
    quant: str
    size_gb: float
    fit: str  # "gpu" | "cpu" (fits RAM, slower) | "too_big"
    ollama_model: str
    downloads: int = 0
    uncensored: bool = False
    fine_tuned: bool = False
    base_model: str = ""
    trusted: bool = False
    other_quants: list[dict[str, Any]] = field(default_factory=list)


Fetch = Callable[[str], Any]
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _http_json(url: str) -> Any:
    with _cache_lock:
        hit = _cache.get(url)
        if hit and time.monotonic() - hit[0] < 3600:
            return hit[1]
    request = urllib.request.Request(url, headers={"User-Agent": "vellum-onboarding"})
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed HF API host
        data = json.loads(response.read().decode("utf-8"))
    with _cache_lock:
        _cache[url] = (time.monotonic(), data)
    return data


def quant_of(filename: str) -> str:
    match = _QUANT_RE.search(filename.rsplit("/", 1)[-1])
    return match.group(1).upper() if match else ""


def gguf_files(tree: list[dict[str, Any]]) -> dict[str, float]:
    """quant -> size in GB for single-file model weights (no projectors, no split shards)."""
    sizes: dict[str, float] = {}
    for entry in tree:
        path = str(entry.get("path") or "")
        name = path.rsplit("/", 1)[-1].casefold()
        if (not name.endswith(".gguf") or name.startswith("mmproj") or re.search(r"-\d{5}-of-\d{5}", name)
                or re.search(r"(?:^|[-_.])(?:mtp|draft|proj)(?:[-_.]|$)", name)):
            continue  # projectors, split shards, draft/multi-token-prediction helpers aren't the model
        quant = quant_of(path)
        size = float(entry.get("size") or (entry.get("lfs") or {}).get("size") or 0) / 1e9
        if quant and size and size > sizes.get(quant, 0):  # the main weights are the largest file
            sizes[quant] = round(size, 2)
    return sizes


def budget(hw: dict[str, Any]) -> tuple[float, float]:
    """(GPU budget, CPU/RAM budget) in GB."""
    return float(hw.get("vram_gb") or 0), max(0.0, float(hw.get("ram_gb") or 0) - 3.0)


def best_quant(sizes: dict[str, float], hw: dict[str, Any]) -> tuple[str, float, str]:
    gpu, cpu = budget(hw)
    ordered = [quant for quant in QUANT_ORDER if quant in sizes]
    for limit, fit in ((gpu, "gpu"), (cpu, "cpu")):
        for quant in ordered:
            if sizes[quant] * HEADROOM <= limit:
                return quant, sizes[quant], fit
    if ordered:
        smallest = min(ordered, key=lambda quant: sizes[quant])
        return smallest, sizes[smallest], "too_big"
    return "", 0.0, "too_big"


def _classify(model: dict[str, Any]) -> tuple[bool, bool, str]:
    tags = [str(tag) for tag in model.get("tags") or []]
    text = " ".join([str(model.get("id") or ""), *tags])
    uncensored = bool(_UNCENSORED_RE.search(text))
    base = next((tag.split(":", 2)[-1] for tag in tags if tag.startswith("base_model:") and tag.count(":") >= 2), "")
    fine_tuned = any(tag.startswith(("base_model:finetune:", "base_model:merge:")) for tag in tags) or uncensored
    return uncensored, fine_tuned, base


def search(query: str, hw: dict[str, Any], *, include_uncensored: bool = False, limit: int = 8,
           fetch: Fetch = _http_json) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"search": query, "filter": "gguf", "sort": "downloads",
                                     "limit": 30, "full": "true"})
    models = fetch(f"{HF_API}/models?{params}") or []
    options: list[ModelOption] = []
    for model in models:
        repo = str(model.get("id") or "")
        uncensored, fine_tuned, base = _classify(model)
        if not repo or (uncensored and not include_uncensored):
            continue
        try:
            sizes = gguf_files(fetch(f"{HF_API}/models/{repo}/tree/main") or [])
        except Exception:  # noqa: BLE001 - one bad repo shouldn't fail the search
            continue
        quant, size, fit = best_quant(sizes, hw)
        if not quant:
            continue
        options.append(ModelOption(
            repo=repo, quant=quant, size_gb=size, fit=fit, ollama_model=f"hf.co/{repo}:{quant}",
            downloads=int(model.get("downloads") or 0), uncensored=uncensored, fine_tuned=fine_tuned,
            base_model=base, trusted=repo.split("/", 1)[0] in TRUSTED_UPLOADERS,
            other_quants=[{"quant": q, "size_gb": sizes[q]} for q in QUANT_ORDER if q in sizes],
        ))
        if len(options) >= limit * 2:
            break
    fit_rank = {"gpu": 0, "cpu": 1, "too_big": 2}
    options.sort(key=lambda o: (fit_rank[o.fit], o.quant in LOW_QUANTS, not o.trusted, o.fine_tuned, -o.downloads))
    return [asdict(option) for option in options[:limit]]


def recommended(hw: dict[str, Any], *, category: str = "general", fetch: Fetch = _http_json) -> list[dict[str, Any]]:
    """A short, trusted-first list for a category, sized to this machine."""
    seen: set[str] = set()
    picks: list[dict[str, Any]] = []
    queries = list(CURATED_QUERIES.get(category, CURATED_QUERIES["general"]))
    gpu, cpu = budget(hw)
    if category == "general" and max(gpu, cpu) < 7:
        queries += list(CURATED_QUERIES["small"])  # tight memory: smaller models at good quality
    for query in queries:
        for option in search(query, hw, limit=3, fetch=fetch):
            if option["repo"] not in seen and option["trusted"] and option["fit"] != "too_big":
                seen.add(option["repo"])
                picks.append(option)
                break
    # Good quality first: a small model at Q4+ beats a big one squeezed to 2-3 bits.
    picks.sort(key=lambda o: (o["fit"] != "gpu", o["quant"] in LOW_QUANTS))
    return picks
