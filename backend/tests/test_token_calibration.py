"""Measured token ratios make local budgets accurate without becoming optimistic."""
from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage

from agent.llm import token_calibration as calibration
from agent.llm.context import ContextBudget, estimate_tokens, project_context


def test_measure_keeps_prose_and_structured_ratios_apart_with_safety():
    texts = {"prose": "prose words " * 200, "structured": '{"json": [1, 2]} ' * 200}
    real = {texts["prose"]: 10 + estimate_tokens(texts["prose"]) // 2,
            texts["structured"]: 10 + int(estimate_tokens(texts["structured"]) * .8)}
    ratios = calibration.measure("ollama/test", lambda text: real.get(text, 10), texts=texts)
    assert abs(ratios["prose"] - .5 * calibration.SAFETY) < .02
    assert abs(ratios["structured"] - .8 * calibration.SAFETY) < .02


def test_ratio_is_bounded_and_missing_models_stay_conservative(tmp_path):
    path = tmp_path / "calibration.json"
    assert calibration.token_ratios("ollama/new", path=path) == (1.0, 1.0)
    calibration.save("ollama/edge", {"prose": .01, "structured": 9}, path=path)
    assert calibration.token_ratios("ollama/edge", path=path) == calibration.BOUNDS


def test_calibrated_budget_compacts_later_and_reports_its_ratio():
    prompt = [SystemMessage(content="Instructions. " * 300)]
    for index in range(8):
        prompt.append(HumanMessage(content=f"Turn {index} " + "detail " * 100, id=f"u{index}"))
    budget = ContextBudget(4096, 512, 512, .8, .5, 300, 2, role="main")
    assert project_context(prompt, [], budget).report["compacted"]
    calibrated = project_context(prompt, [], ContextBudget(4096, 512, 512, .8, .5, 300, 2, role="main", token_ratio=(.6, .9)))
    assert not calibrated.report["compacted"]
    assert calibrated.report["token_ratio"] == {"prose": .6, "structured": .9}
    assert estimate_tokens("x" * 300) == 100  # the ratio applies only inside a projection


def test_structured_text_gets_the_denser_ratio():
    from agent.llm.context import _TOKEN_RATIO
    token = _TOKEN_RATIO.set((.5, 1.0))
    try:
        prose, schema = "plain words " * 50, '{"a": [1, 2], "b": {"c": "d"}} ' * 20
        assert estimate_tokens(prose) < len(prose.encode()) / 3 * .6
        assert estimate_tokens(schema) == -(-len(schema.encode()) // 3)
        assert estimate_tokens({"k": "v"}) == estimate_tokens('{"k": "v"}')
    finally:
        _TOKEN_RATIO.reset(token)


def test_calibration_never_starts_when_disabled(monkeypatch):
    started = []
    monkeypatch.setattr(calibration.threading, "Thread", lambda *a, **k: started.append(k) or SimpleNamespace(start=lambda: None))
    calibration.ensure_calibrated("ollama/test", SimpleNamespace(context_token_calibration=False))
    calibration.ensure_calibrated("openrouter/test", SimpleNamespace(context_token_calibration=True))
    assert started == []
