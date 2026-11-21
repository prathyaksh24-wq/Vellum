"""Local context windows sized to the GPU, with explicit and Settings overrides."""
from types import SimpleNamespace

import pytest

from agent.llm import context_sizing as sizing


def placement(fits_up_to=None, on_gpu_ratio=1.0, cpu=False):
    loads = []
    def load(num_ctx):
        loads.append(num_ctx)
        size = 8_000_000_000 + num_ctx * 2_000
        if cpu:
            return {"size": size, "size_vram": 0}
        fits = fits_up_to is not None and num_ctx <= fits_up_to
        return {"size": size, "size_vram": size if fits else int(size * on_gpu_ratio)}
    return load, loads


def test_largest_window_that_stays_on_the_gpu_wins():
    load, loads = placement(fits_up_to=65_536, on_gpu_ratio=.9)
    result = sizing.measure(load, model_max=262_144)
    assert result["window"] == 65_536 and result["placement"] == "gpu"
    assert loads == [131_072, 65_536]  # stops at the first fit


def test_candidates_never_exceed_the_model_maximum():
    load, loads = placement(fits_up_to=131_072)
    assert sizing.measure(load, model_max=40_000)["window"] == 32_768 and loads[0] == 32_768


def test_cpu_only_and_partial_offload_fall_back_safely():
    load, _ = placement(cpu=True)
    result = sizing.measure(load, model_max=262_144)
    assert result["placement"] == "cpu" and result["window"] == sizing.CPU_WINDOW
    partial, _ = placement(fits_up_to=None, on_gpu_ratio=.6)
    result = sizing.measure(partial, model_max=262_144)
    assert result["placement"] == "partial" and result["window"] == sizing.DEFAULT_WINDOW


def settings(**kwargs):
    return SimpleNamespace(ollama_context_length=kwargs.pop("ollama", 32_768), cloud_context_length=kwargs.pop("cloud", None),
                           context_auto_size=True, model_fields_set=kwargs.pop("explicit", set()), **kwargs)


def test_precedence_environment_then_settings_then_measured_then_default():
    model = "ollama/gemma4:12b"
    assert sizing.local_window(model, settings()) == sizing.DEFAULT_WINDOW
    sizing.record(model, {"window": 131_072, "placement": "gpu", "tried": []})
    assert sizing.local_window(model, settings()) == 131_072
    sizing.set_preferences(local=16_384)
    assert sizing.local_window(model, settings()) == 16_384
    assert sizing.local_window(model, settings(ollama=65_536, explicit={"ollama_context_length"})) == 65_536
    assert sizing.describe(settings(), model)["local_source"] == "settings"
    sizing.set_preferences(local="auto")
    assert sizing.describe(settings(), model)["local_source"] == "measured"


def test_cloud_cap_from_settings_or_environment():
    assert sizing.cloud_cap(settings()) is None
    sizing.set_preferences(cloud=200_000)
    assert sizing.cloud_cap(settings()) == 200_000
    assert sizing.cloud_cap(settings(cloud=500_000)) == 500_000
    sizing.set_preferences(cloud="full")
    assert sizing.cloud_cap(settings()) is None


@pytest.mark.parametrize("local, cloud", [(12_345, None), (None, 7), ("big", None)])
def test_only_supported_choices_are_saved(local, cloud):
    with pytest.raises(ValueError):
        sizing.set_preferences(local=local, cloud=cloud)


def test_measurement_happens_once_and_only_when_automatic():
    model = "ollama/gemma4:12b"
    assert sizing.needs_measurement(model, settings())
    assert not sizing.needs_measurement("anthropic/claude-opus-5", settings())
    assert not sizing.needs_measurement(model, settings(explicit={"ollama_context_length"}))
    sizing.set_preferences(local=65_536)
    assert not sizing.needs_measurement(model, settings())
    sizing.set_preferences(local="auto")
    sizing.record(model, {"window": 65_536, "placement": "gpu", "tried": []})
    assert not sizing.needs_measurement(model, settings())
    disabled = settings()
    disabled.context_auto_size = False
    assert not sizing.needs_measurement("ollama/other:7b", disabled)
