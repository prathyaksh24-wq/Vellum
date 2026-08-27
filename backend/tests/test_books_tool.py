from __future__ import annotations

import json

from agent.agents.base import SpecialistResponse
from agent.master.runtime import DelegationRunResult
from agent.tools import books as books_tool


class FakeRuntime:
    def __init__(self, response: SpecialistResponse) -> None:
        self.response = response
        self.requests = []

    def delegate(self, request):
        self.requests.append(request)
        return DelegationRunResult(
            run_id="run-1",
            task_id="task-1",
            parent_thread_id=request.parent_thread_id,
            profile_id="BooksAgent",
            profile_version=2,
            executor="deterministic",
            cache_status="bypass",
            cache_reason="profile_cache_disabled",
            started_at="2026-08-20T00:00:00+00:00",
            finished_at="2026-08-20T00:00:01+00:00",
            response=self.response,
        )


def test_books_agent_tool_delegates_with_thread_context(monkeypatch) -> None:
    runtime = FakeRuntime(
        SpecialistResponse(
            agent="BooksAgent",
            status="needs_fetch",
            summary="No matching installed Book evidence was found.",
            structured_payload={
                "books_agent": {
                    "schema_version": "books-agent-response-v1",
                    "answer": "No matching installed Book evidence was found.",
                    "answer_claim_ids": [],
                    "claims": [],
                    "evidence": [],
                    "judgment": None,
                    "user_learning_events": [],
                    "uncertainty": ["No matching installed Book evidence was found."],
                    "status": "abstained",
                }
            },
        )
    )
    monkeypatch.setattr(books_tool, "_get_books_runtime", lambda: runtime)

    result = json.loads(
        books_tool.books_agent.func(
            query="What did the 45th law mean?",
            config={"configurable": {"thread_id": "thread-books", "user_id": "user-books"}},
        )
    )

    assert result["agent"] == "BooksAgent"
    assert result["structured_payload"]["books_agent"]["status"] == "abstained"
    assert runtime.requests[0].agent_id == "BooksAgent"
    assert runtime.requests[0].parent_thread_id == "thread-books"
    assert runtime.requests[0].user_id == "user-books"


def test_books_agent_tool_rejects_empty_query_without_building_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        books_tool,
        "_get_books_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("runtime should not be built")),
    )

    result = json.loads(books_tool.books_agent.func(query="   "))

    assert result["status"] == "blocked"
    assert result["agent"] == "BooksAgent"
    assert result["structured_payload"]["books_agent"]["status"] == "failed"


def test_books_agent_tool_returns_typed_failure_when_runtime_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        books_tool,
        "_get_books_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )

    result = json.loads(books_tool.books_agent.func(query="What does the Book say?"))

    assert result["status"] == "error"
    assert result["structured_payload"]["books_agent"]["status"] == "failed"
