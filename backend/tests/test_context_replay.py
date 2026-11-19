"""The offline replay counts compaction, overflow and removed tool evidence."""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.llm.context import ContextBudget
from agent.llm.context_replay import replay_thread, summarize


def thread(turns):
    messages = []
    for index in range(turns):
        messages += [HumanMessage(content=f"Question {index} " + "context " * 80, id=f"u{index}"),
                     AIMessage(content="", id=f"c{index}", tool_calls=[{"name": "web_search", "args": {}, "id": f"t{index}"}]),
                     ToolMessage(content='{"result": "' + "evidence " * 120 + '"}', tool_call_id=f"t{index}", id=f"r{index}"),
                     AIMessage(content="Answer " * 40, id=f"a{index}")]
    return messages


def test_replay_reports_compaction_and_removed_tool_evidence_without_overflow():
    budget = ContextBudget(4096, 512, 512, .8, .5, 300, 2, role="main")
    report = replay_thread("t", thread(12), [SystemMessage(content="Instructions")], [], budget)
    assert report.model_calls == 24 and report.tool_results == 12
    assert report.compactions > 0 and report.exceeded == 0
    assert 0 < report.tool_results_removed < 12 and report.tool_tokens_removed > 0
    summary = summarize([report], budget)
    assert summary["compaction_rate"] > 0 and summary["tool_evidence_removed_share"] > 0


def test_replay_counts_calls_that_cannot_fit():
    budget = ContextBudget(4096, 512, 512, .8, .5, 300, 2, role="main")
    report = replay_thread("t", thread(2), [SystemMessage(content="Protected. " * 2000)], [], budget)
    assert report.exceeded == report.model_calls == 4


def test_removed_results_with_evidence_ids_count_as_recoverable():
    budget = ContextBudget(4096, 512, 512, .8, .5, 300, 2, role="main")
    longer = lambda m: m.model_copy(update={"content": m.content * 2})  # past the digest excerpt
    plain = replay_thread("t", thread(12), [SystemMessage(content="Instructions")], [], budget, prepare_tool=longer)
    kept = replay_thread("t", thread(12), [SystemMessage(content="Instructions")], [], budget,
                         prepare_tool=lambda m: longer(m).model_copy(update={"additional_kwargs": {"vellum_evidence_id": "ev_x"}}))
    assert plain.tool_tokens_unrecoverable == plain.tool_tokens_removed > 0
    assert kept.tool_tokens_removed > 0 and kept.tool_tokens_unrecoverable == 0
