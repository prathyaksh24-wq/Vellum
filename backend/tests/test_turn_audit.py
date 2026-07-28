import json
import asyncio

from agent import api
from agent.telemetry.turn_audit import TurnAudit


EXPECTED_FIELDS = {
    "timestamp",
    "thread_id",
    "model",
    "provider",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "latency_first_token_ms",
    "latency_total_ms",
    "tools_called",
    "privacy_class",
    "outcome",
    "retrieval_confidence",
    "followup_detected",
    "saved",
    "regenerated",
}


def test_turn_audit_writes_one_metadata_only_record(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    audit = TurnAudit(
        thread_id="thread-1",
        model="google/gemma-3-12b-it",
        provider="openrouter",
        privacy_class="GREEN",
        path=path,
        saved=True,
    )
    audit.observe_usage({"input_tokens": 10, "output_tokens": 4})
    audit.mark_first_token()

    assert audit.finalize("completed", tools_called=["search", "search", "vault.read"])
    assert not audit.finalize("failed")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record) == EXPECTED_FIELDS
    assert record["thread_id"] == "thread-1"
    assert record["total_tokens"] == 14
    assert record["tools_called"] == ["search", "vault.read"]
    assert record["privacy_class"] == "GREEN"
    assert record["outcome"] == "completed"
    assert "prompt" not in record
    assert "response" not in record


def test_audited_stream_records_emitted_error_as_failed(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    audit = TurnAudit(
        thread_id="thread-error",
        model="google/gemma-3-12b-it",
        provider="openrouter",
        privacy_class="GREEN",
        path=path,
    )

    async def error_stream():
        yield 'event: error\ndata: {"error":"provider failed"}\n\n'

    async def consume() -> None:
        async for _chunk in api._audited_turn_stream(error_stream(), audit):
            pass

    asyncio.run(consume())

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["outcome"] == "failed"
