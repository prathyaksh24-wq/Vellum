import asyncio
import json

from agent import api
from agent.setup_hardware import Hardware, recommend


def test_gpu_with_room_runs_the_12b_model_locally():
    rec = recommend(Hardware(ram_gb=15.2, free_disk_gb=700, cpu_cores=32, gpu_name="RTX 5070 Ti", vram_gb=11.9,
                             ollama_installed=True))
    assert (rec.mode, rec.model) == ("local", "gemma4:12b")
    assert rec.reasons[0] == "Runs on your RTX 5070 Ti (12 GB)"


def test_8gb_laptop_without_gpu_gets_the_9b_model_on_cpu_and_an_ollama_note():
    rec = recommend(Hardware(ram_gb=7.8, free_disk_gb=120, cpu_cores=8))
    assert (rec.mode, rec.model, rec.size_gb) == ("local", "qwen3.5:9b", 5.5)
    assert "slower" in rec.reasons[0] and "Ollama will need to be installed to run it" in rec.reasons


def test_low_memory_or_disk_recommends_cloud_with_reasons():
    small = recommend(Hardware(ram_gb=4, free_disk_gb=200, cpu_cores=4))
    assert small.mode == "cloud" and "8 GB minimum" in small.reasons[0]
    assert small.cloud_options == ["openrouter", "groq"]
    full_disk = recommend(Hardware(ram_gb=32, free_disk_gb=5, cpu_cores=8))
    assert full_disk.mode == "cloud" and "Only 5 GB free" in full_disk.reasons[0]


def test_setup_complete_applies_the_model_and_never_saves_keys(monkeypatch, tmp_path):
    saved, dispatched, restarted = {}, [], []
    monkeypatch.setattr(api, "_write_setup_state", lambda payload: saved.update(payload))

    def dispatch(action_id, arguments):
        dispatched.append((action_id, arguments))
        return type("Receipt", (), {"result": {"model": {"id": arguments["model"]}}})()

    monkeypatch.setattr(api, "_dispatch_compat_action", dispatch)
    from agent.memory.engines import runtime

    monkeypatch.setattr(runtime, "restart_engines", lambda: restarted.append(True))
    result = asyncio.run(api.setup_complete(api.SetupStateBody(state={
        "apply_model": "ollama/qwen3.5:9b", "cloud": {"provider": "groq"},
        "groq_api_key": "gsk-should-not-be-saved", "apiKey": "nope"})))

    assert result["applied"] == {"model": "ollama/qwen3.5:9b"}
    assert dispatched == [(api.DEFAULT_MODEL_SET_ACTION_ID, {"model": "ollama/qwen3.5:9b"})]
    assert restarted == [True]
    assert "gsk-should-not-be-saved" not in json.dumps(saved) and "apiKey" not in saved
    assert saved["cloud"] == {"provider": "groq"} and saved["completed_at"]
