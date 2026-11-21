"""Onboarding shows each model's context window for this computer."""
import io
import json

from agent.setup_flow import ModelPull
from agent.setup_hardware import Hardware, recommend
from agent.setup_models import estimate_context

HW = {"vram_gb": 11.9, "ram_gb": 15.2}


def test_estimate_is_a_gpu_floor_and_a_fixed_cpu_window():
    assert estimate_context("unsloth/Qwen3.5-9B-GGUF", 5.5, "gpu", HW) == 32768
    assert estimate_context("unsloth/gemma-4-12b-it-GGUF", 7.6, "gpu", HW) == 16384  # floor; measured is higher
    assert estimate_context("Qwen/Qwen3.8-27B-GGUF", 16.5, "cpu", HW) == 32768
    assert estimate_context("x/model-70b", 40, "too_big", HW) == 0
    assert estimate_context("x/tiny-model", 2.0, "gpu", HW) >= 65536  # unknown size: inferred from the download


def opener(lines):
    class Response(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    return lambda request, timeout: Response(b"\n".join(json.dumps(line).encode() for line in lines))


def test_download_is_followed_by_a_measured_window():
    pull = ModelPull(opener=opener([{"status": "success"}]), on_done=lambda model: "ollama/" + model,
                     on_sized=lambda model_id: {"window": 131072, "placement": "gpu"})
    pull._run("http://127.0.0.1:11434", "gemma4:12b")
    status = pull.snapshot()
    assert status["state"] == "done" and status["context_state"] == "sized"
    assert status["context_window"] == 131072 and status["context_placement"] == "gpu"


def test_a_failed_measurement_still_leaves_the_model_ready():
    def broken(model_id):
        raise RuntimeError("ollama busy")
    pull = ModelPull(opener=opener([{"status": "success"}]), on_done=lambda model: "ollama/" + model, on_sized=broken)
    pull._run("http://127.0.0.1:11434", "gemma4:12b")
    status = pull.snapshot()
    assert status["state"] == "done" and status["context_state"] == "skipped" and status["context_window"] == 0


def hardware(vram):
    return Hardware(ram_gb=15.2, free_disk_gb=500, cpu_cores=16, cpu_name="cpu", gpu_name="GPU", vram_gb=vram,
                    ollama_installed=True, ollama_running=True, platform="win32")


def test_recommendation_states_the_context_window_measured_or_estimated():
    from agent.llm.context_sizing import record
    reasons = recommend(hardware(11.9)).reasons
    assert any(reason.startswith("Context window: at least") for reason in reasons)
    record("ollama/gemma4:12b", {"window": 131072, "placement": "gpu", "tried": []})
    assert "Context window: 128k tokens, measured on this computer" in recommend(hardware(11.9)).reasons
