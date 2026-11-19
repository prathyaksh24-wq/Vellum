"""Tool results that leave the prompt stay retrievable, scoped to their conversation."""
from datetime import timedelta
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.conversations.evidence import EVIDENCE_ID, attach_evidence, evidence_store, _now
from agent.graph.tool_reuse import MAX_RESULT_CHARS, keep_evidence
from agent.llm.context import ContextBudget, digest_message, project_context


def test_pages_and_passages_are_readable_only_from_the_owning_conversation():
    store = evidence_store()
    content = "\n".join(f"Issue {n}: {'payment retry fails' if n == 777 else 'routine work'} " + "x" * 40
                        for n in range(1000))
    evidence_id = store.put(content, tool="linear.list_issues", thread_id="chat-a")
    first = store.read(evidence_id, "chat-a")
    assert first["ok"] and first["page"] == 1 and first["pages"] > 1 and first["text"] == content[:6000]
    assert store.read(evidence_id, "chat-a", page=2)["text"] == content[6000:12000]
    found = store.read(evidence_id, "chat-a", query="payment retry")
    assert any("Issue 777" in match["text"] for match in found["matches"])
    assert not store.read(evidence_id, "chat-b")["ok"]


def test_unclaimed_results_become_readable_only_after_the_thread_claims_them():
    store = evidence_store()
    evidence_id = store.put("raw connector output " * 100, tool="github.search")
    assert not store.read(evidence_id, "chat-a")["ok"]
    assert store.claim([evidence_id], "chat-a") == 1
    assert store.claim([evidence_id], "chat-b") == 0  # never re-bound to another chat
    assert store.read(evidence_id, "chat-a")["ok"]


def test_deletion_and_retention():
    store = evidence_store()
    kept = store.put("a" * 2000, thread_id="chat-a")
    store.put("b" * 2000, thread_id="chat-b")
    assert store.delete_thread("chat-b") == 1
    store.put("unclaimed", tool="x")
    assert store.prune(now=_now() + timedelta(hours=2), force=True) == 1
    assert store.read(kept, "chat-a")["ok"]
    assert store.prune(now=_now() + timedelta(days=91), force=True) == 1
    assert not store.read(kept, "chat-a")["ok"]


def test_trimmed_mcp_projections_point_at_their_full_original():
    raw = json.dumps([{"id": n, "title": f"Issue {n}", "body": "detail " * 50} for n in range(200)])
    summary = attach_evidence("<MCP_RESULT_SUMMARY>\nfacts: ...\n</MCP_RESULT_SUMMARY>", raw, tool="linear.list", structured=False)
    assert summary.rstrip().endswith("</MCP_RESULT_SUMMARY>") and EVIDENCE_ID.search(summary)
    structured = json.loads(attach_evidence(json.dumps({"data": [], "truncated": True}), raw, tool="github.list", structured=True))
    assert EVIDENCE_ID.fullmatch(structured["evidence_id"])
    assert attach_evidence("same", "same", tool="x", structured=False) == "same"


def test_tool_step_claims_saves_and_bounds_results():
    store = evidence_store()
    connector_id = store.put("full connector output " * 200, tool="notion.search")
    big = "row of data " * (MAX_RESULT_CHARS // 8)
    messages = [ToolMessage(content=f"summary\nevidence_id: {connector_id}", tool_call_id="1", name="notion_mcp_read"),
                ToolMessage(content=big, tool_call_id="2", name="web_search"),
                ToolMessage(content="small", tool_call_id="3", name="web_search")]
    kept = keep_evidence(messages, "chat-a")
    assert kept[0].additional_kwargs["vellum_evidence_id"] == connector_id and store.read(connector_id, "chat-a")["ok"]
    preview = json.loads(kept[1].content)
    assert preview["incomplete"] and preview["total_chars"] == len(big) and len(kept[1].content) < len(big)
    assert store.read(preview["evidence_id"], "chat-a")["total_chars"] == len(big)
    assert kept[2] is messages[2]
    assert keep_evidence(messages, "") == messages


def test_compaction_digest_lists_removed_tool_results_by_evidence_id():
    prompt = [SystemMessage(content="Instructions")]
    for n in range(10):
        prompt += [HumanMessage(content=f"Question {n} " + "context " * 80, id=f"u{n}"),
                   AIMessage(content="", id=f"c{n}", tool_calls=[{"name": "web_search", "args": {}, "id": f"t{n}"}]),
                   ToolMessage(content="evidence " * 150, tool_call_id=f"t{n}", id=f"r{n}", name="web_search",
                               additional_kwargs={"vellum_evidence_id": f"ev_{n:020d}"}),
                   AIMessage(content="Answer " * 30, id=f"a{n}")]
    result = project_context(prompt, [], ContextBudget(4096, 512, 512, .8, .5, 400, 2, role="main"))
    assert result.report["compacted"]
    listed = [item["evidence_id"] for item in result.digest["evidence"]]
    assert listed and listed[0] == max(listed)  # newest first
    assert "conversation_history(evidence_id=...)" in digest_message(result.digest).content


def test_conversation_history_reads_evidence_for_the_current_chat_only():
    from agent.tools.conversation_history import conversation_history
    evidence_id = evidence_store().put("stored result " * 300, tool="web_search", thread_id="chat-a")
    mine = json.loads(conversation_history.invoke({"evidence_id": evidence_id}, config={"configurable": {"thread_id": "chat-a"}}))
    other = json.loads(conversation_history.invoke({"evidence_id": evidence_id}, config={"configurable": {"thread_id": "chat-b"}}))
    assert mine["ok"] and mine["untrusted_tool_evidence"] and not other["ok"]


def test_deleting_a_conversation_deletes_its_evidence(tmp_path):
    from agent.memory.sessions import SessionsReader
    store = evidence_store(tmp_path / "evidence.db")
    evidence_id = store.put("kept " * 500, thread_id="chat-a")
    SessionsReader(checkpoints_db=tmp_path / "checkpoints.db", sessions_db=tmp_path / "sessions.db").delete("chat-a")
    assert not store.read(evidence_id, "chat-a")["ok"]
