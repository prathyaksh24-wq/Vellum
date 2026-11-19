"""Long chats keep their thread: summaries, working state, and the four context tools."""
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.conversations import context_archive as archive_module
from agent.conversations.context_archive import context_archive, transcript_lines
from agent.llm.context import digest_message, summary_budget


def turns(start, count, *, size=60):
    messages = []
    for n in range(start, start + count):
        messages += [HumanMessage(content=f"Turn {n}: please handle invoice INV-{n} " + "detail " * size, id=f"u{n}"),
                     AIMessage(content=f"Handled INV-{n}.", id=f"a{n}")]
    return messages


def fake_summarizer(calls):
    def summarize(working, text, kind):
        calls.append(kind)
        ids = sorted(set(part for part in text.split() if part.startswith("INV-")))
        state = dict(working)
        state["facts"] = (state.get("facts", []) + ids)[-8:]
        state["goal"] = "Reconcile invoices"
        return {"summary": f"{kind}: covered {', '.join(ids) or 'merged parts'}", "working_state": state}
    return summarize


def test_ranges_are_summarized_after_the_turn_and_shape_the_working_state():
    archive, calls = context_archive(), []
    first = archive.record_range("chat", turns(0, 3))
    assert first and archive.blocks("chat")[0]["summary"] is None
    assert archive.view("chat", budget_tokens=2000) == {}  # nothing to show until summarized
    assert archive.summarize_pending("chat", fake_summarizer(calls)) == 1
    view = archive.view("chat", budget_tokens=2000)
    assert view["working_state"]["goal"] == "Reconcile invoices"
    assert "INV-0" in view["summaries"][0]["summary"] and "u0" in view["covered_ids"]


def test_large_ranges_split_and_old_summaries_merge_into_higher_levels():
    archive, calls = context_archive(), []
    big = turns(0, 6, size=900)  # each user turn is about 6,300 characters
    assert len(archive.record_range("chat", big)) > 1
    for n in range(6, 16):
        archive.record_range("chat", turns(n, 1))
    archive.summarize_pending("chat", fake_summarizer(calls))
    assert "merge" in calls
    levels = [block["level"] for block in archive.blocks("chat")]
    assert max(levels) >= 1 and len(levels) <= archive_module.MERGE_AFTER + 1
    merged = next(block for block in archive.blocks("chat") if block["level"] >= 1)
    opened = archive.decompress("chat", merged["block_id"])
    assert opened["ok"] and len(opened["parts"]) == archive_module.MERGE_COUNT


def test_view_fits_the_budget_and_lists_older_summaries_by_id():
    archive = context_archive()
    for n in range(5):
        archive.record_range("chat", turns(n, 1))
    archive.summarize_pending("chat", fake_summarizer([]))
    tight = archive.view("chat", budget_tokens=60)
    roomy = archive.view("chat", budget_tokens=5000)
    assert len(tight["summaries"]) < len(roomy["summaries"]) == 5
    assert tight["older_summaries"] and "INV-4" in tight["summaries"][-1]["summary"]  # newest kept


def test_failed_summaries_leave_excerpts_in_charge_and_stop_retrying():
    archive = context_archive()
    archive.record_range("chat", turns(0, 1))
    def broken(*args):
        raise ValueError("model unavailable")
    for _ in range(3):
        archive.summarize_pending("chat", broken)
    assert archive.blocks("chat")[0]["attempts"] == archive_module.MAX_ATTEMPTS
    assert archive.view("chat", budget_tokens=2000) == {}


def test_model_output_is_sanitized():
    clean = archive_module._validated({"summary": " ok ", "working_state": {
        "goal": "g" * 900, "decisions": ["d"] * 20, "facts": "not a list", "unknown": ["x"]}})
    assert clean["summary"] == "ok" and len(clean["working_state"]["goal"]) == 300
    assert len(clean["working_state"]["decisions"]) == 8 and "facts" not in clean["working_state"]


def test_digest_shows_summaries_and_hides_the_excerpts_they_cover():
    digest = {"entries": [{"role": "human", "message_id": "u0", "excerpt": "old"},
                          {"role": "human", "message_id": "u9", "excerpt": "recent"}],
              "summaries": [{"block_id": "blk_a", "level": 0, "summary": "Invoices 0-3 reconciled"}],
              "working_state": {"goal": "Reconcile invoices"}, "covered_ids": ["u0"]}
    content = digest_message(digest).content
    assert "Invoices 0-3 reconciled" in content and "Reconcile invoices" in content
    assert '"recent"' in content and '"old"' not in content and "covered_ids" not in content
    assert digest_message({"summaries": [{"block_id": "b", "summary": "s"}]}) is not None
    assert digest_message({}) is None


def test_summary_budget_scales_with_the_window_for_continuity():
    assert summary_budget(32768) < summary_budget(65536) < summary_budget(131072) <= 16384
    assert summary_budget(4096) == 512


def test_tool_results_are_cited_by_evidence_id_in_transcripts():
    lines = transcript_lines([ToolMessage(content="row " * 1000, tool_call_id="t", name="linear_read",
                                          additional_kwargs={"vellum_evidence_id": "ev_abc"})])
    assert "evidence_id=ev_abc" in lines[0][1] and len(lines[0][1]) < 2200


def test_the_four_context_tools_are_scoped_to_the_current_chat():
    from agent.tools.context_tools import compress, context_status, decompress, search_context
    archive = context_archive()
    block = archive.record_range("chat", turns(0, 2))[0]
    archive.summarize_pending("chat", fake_summarizer([]))
    archive.note_report("chat", {"context_window": 32768, "estimated_input_tokens": 16000, "input_limit": 29081,
                                 "layers": {"instructions": 8000}, "compaction_count": 1, "summary_tokens": 2621})
    mine = {"configurable": {"thread_id": "chat"}}
    other = {"configurable": {"thread_id": "other"}}
    status = json.loads(context_status.invoke({}, config=mine))
    assert status["used_share"] == round(16000 / 32768, 3) and status["summaries"][0]["ready"]
    found = json.loads(search_context.invoke({"query": "INV-1 invoice"}, config=mine))
    assert any("INV-1" in hit["text"] for hit in found["summaries_and_compacted"])
    assert json.loads(search_context.invoke({"query": "INV-1"}, config=other))["summaries_and_compacted"] == []
    opened = json.loads(decompress.invoke({"block_id": block}, config=mine))
    assert opened["ok"] and "INV-0" in opened["original"]
    assert not json.loads(decompress.invoke({"block_id": block}, config=other))["ok"]
    assert json.loads(compress.invoke({"focus": "invoices"}, config=mine))["status"] == "scheduled"
    assert archive.take_compaction_request("chat") == {"focus": "invoices"}
    assert archive.take_compaction_request("chat") is None


def test_deleting_a_conversation_deletes_its_summaries(tmp_path):
    from agent.memory.sessions import SessionsReader
    archive = context_archive(tmp_path / "evidence.db")
    archive.record_range("chat", turns(0, 1))
    SessionsReader(checkpoints_db=tmp_path / "checkpoints.db", sessions_db=tmp_path / "sessions.db").delete("chat")
    assert archive.blocks("chat", include_merged=True) == []


def test_summaries_never_start_while_disabled(monkeypatch):
    started = []
    monkeypatch.setattr(archive_module.threading, "Thread", lambda *a, **k: started.append(1))
    archive_module.turn_finished("chat")  # tests run with CONTEXT_SUMMARIES_ENABLED=false
    assert started == []
