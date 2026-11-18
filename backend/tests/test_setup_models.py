from agent import setup_models as catalog

GB = 1e9


def _tree(prefix, quants, extra=()):
    files = [{"path": f"{prefix}-{q}.gguf", "size": int(size * GB)} for q, size in quants.items()]
    return files + [{"path": path, "size": int(size * GB)} for path, size in extra]


REPOS = {
    "unsloth/Qwen3.5-9B-GGUF": {
        "meta": {"id": "unsloth/Qwen3.5-9B-GGUF", "downloads": 900, "tags": ["gguf", "base_model:quantized:Qwen/Qwen3.5-9B"]},
        "tree": _tree("Qwen3.5-9B", {"Q8_0": 9.5, "Q6_K": 7.4, "Q5_K_M": 6.5, "Q4_K_M": 5.6, "IQ2_M": 3.6},
                      extra=[("mmproj-F16.gguf", 0.9), ("Qwen3.5-9B-MTP-Q8_0.gguf", 0.4),
                             ("Qwen3.5-9B-Q8_0-00001-of-00002.gguf", 5.0)]),
    },
    "SomeUser/Qwen3.5-9B-Uncensored-Heretic-GGUF": {
        "meta": {"id": "SomeUser/Qwen3.5-9B-Uncensored-Heretic-GGUF", "downloads": 5000,
                 "tags": ["gguf", "uncensored", "base_model:finetune:Qwen/Qwen3.5-9B"]},
        "tree": _tree("q", {"Q4_K_M": 5.6}),
    },
    "Fan/Qwen3.5-9B-Roleplay-GGUF": {
        "meta": {"id": "Fan/Qwen3.5-9B-Roleplay-GGUF", "downloads": 50,
                 "tags": ["gguf", "base_model:finetune:Qwen/Qwen3.5-9B"]},
        "tree": _tree("q", {"Q4_K_M": 5.6}),
    },
}


def fake_fetch(url):
    if "/tree/main" in url:
        repo = url.split("/models/", 1)[1].rsplit("/tree/", 1)[0]
        return REPOS[repo]["tree"]
    return [repo["meta"] for repo in sorted(REPOS.values(), key=lambda r: -r["meta"]["downloads"])]


def test_files_skip_projectors_shards_and_draft_helpers():
    sizes = catalog.gguf_files(REPOS["unsloth/Qwen3.5-9B-GGUF"]["tree"])
    assert sizes["Q8_0"] == 9.5  # not the 0.4 GB MTP helper, not a shard
    assert "F16" not in sizes and len(sizes) == 5


def test_best_quant_prefers_gpu_then_ram():
    sizes = catalog.gguf_files(REPOS["unsloth/Qwen3.5-9B-GGUF"]["tree"])
    assert catalog.best_quant(sizes, {"vram_gb": 11.9, "ram_gb": 15.2}) == ("Q8_0", 9.5, "gpu")
    assert catalog.best_quant(sizes, {"vram_gb": 8, "ram_gb": 16}) == ("Q5_K_M", 6.5, "gpu")
    assert catalog.best_quant(sizes, {"vram_gb": 0, "ram_gb": 7.8}) == ("IQ2_M", 3.6, "cpu")
    assert catalog.best_quant(sizes, {"vram_gb": 0, "ram_gb": 4})[2] == "too_big"


def test_uncensored_models_are_hidden_unless_asked_and_official_ranks_first():
    hw = {"vram_gb": 11.9, "ram_gb": 15.2}
    default = catalog.search("qwen3.5 9b", hw, fetch=fake_fetch)
    assert [o["repo"] for o in default] == ["unsloth/Qwen3.5-9B-GGUF", "Fan/Qwen3.5-9B-Roleplay-GGUF"]
    assert default[0]["ollama_model"] == "hf.co/unsloth/Qwen3.5-9B-GGUF:Q8_0" and default[0]["trusted"]
    assert default[1]["fine_tuned"] and default[1]["base_model"] == "Qwen/Qwen3.5-9B"

    opted_in = catalog.search("qwen3.5 9b", hw, include_uncensored=True, fetch=fake_fetch)
    flagged = [o for o in opted_in if o["uncensored"]]
    assert [o["repo"] for o in flagged] == ["SomeUser/Qwen3.5-9B-Uncensored-Heretic-GGUF"]


def test_recommended_lists_only_trusted_models_that_fit():
    picks = catalog.recommended({"vram_gb": 11.9, "ram_gb": 15.2}, fetch=fake_fetch)
    assert picks and all(p["trusted"] and p["fit"] != "too_big" and not p["uncensored"] for p in picks)
