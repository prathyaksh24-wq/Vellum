"""Offline replay of real conversations through Vellum's context projection.

Measures how the context manager behaves on recorded threads without calling a
model: how often a model call needs compaction, how often it is rejected with
ContextBudgetExceeded, how full the window gets, and how much tool evidence
leaves the prompt (and therefore cannot be recovered today).

Read-only: the checkpoint database is copied before it is opened, and only
numbers are reported. Message text never leaves this process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from agent.llm.context import ContextBudget, ContextBudgetExceeded, project_context, prompt_tokens


def _role(message: Any) -> str:
    return str(getattr(message, "type", "") or getattr(message, "role", ""))


@dataclass
class ThreadReport:
    thread_id: str
    messages: int = 0
    model_calls: int = 0
    compactions: int = 0
    exceeded: int = 0
    peak_tokens: int = 0
    tool_results: int = 0
    tool_tokens: int = 0
    tool_results_removed: int = 0
    tool_tokens_removed: int = 0
    pressure: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if key != "pressure"}


def replay_thread(thread_id: str, messages: Sequence[Any], prefix: Sequence[Any], tools: Sequence[Any],
                  budget: ContextBudget, *, project: Callable = project_context) -> ThreadReport:
    """Replay the agent loop: the context node runs before every model call.

    `prefix` stands in for the instructions/memory/retrieval messages that
    `vellum_prompt` prepends on every call; `messages` is the thread's full,
    uncompacted message stream in order.
    """
    report = ThreadReport(thread_id, messages=len(messages))
    state: list[Any] = []
    for message in messages:
        if _role(message) == "ai":
            report.model_calls += 1
            prompt = [*prefix, *state]
            try:
                projection = project(prompt, tools, budget)
            except ContextBudgetExceeded:
                report.exceeded += 1
                report.peak_tokens = max(report.peak_tokens, prompt_tokens(prompt, tools))
            else:
                size = projection.report["estimated_input_tokens"]
                report.peak_tokens = max(report.peak_tokens, size)
                report.pressure.append(size / budget.window)
                if projection.report["compacted"]:
                    report.compactions += 1
                    removed = set(projection.removed_ids)
                    for item in state:
                        if _role(item) == "tool" and str(getattr(item, "id", "")) in removed:
                            report.tool_results_removed += 1
                            report.tool_tokens_removed += prompt_tokens([item]) - 20
                    keep = {id(item) for item in prefix}
                    state = [item for item in projection.messages if id(item) not in keep]
        state.append(message)
        if _role(message) == "tool":
            report.tool_results += 1
            report.tool_tokens += prompt_tokens([message]) - 20
    return report


def full_message_streams(checkpoint_db: Path, *, min_messages: int = 0) -> Iterable[tuple[str, list[Any]]]:
    """Rebuild each thread's uncompacted stream from its checkpoint history.

    Compaction removes messages from the latest state, but earlier checkpoints
    still hold them; the union by message ID, in first-seen order, is the
    stream the agent actually produced.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    with tempfile.TemporaryDirectory(prefix="vellum-replay-") as folder:
        copy = Path(folder) / "checkpoints.db"
        source = sqlite3.connect(f"file:{checkpoint_db.as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(copy)
        source.backup(target)
        source.close()
        saver = SqliteSaver(target)
        threads = [row[0] for row in target.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id")]
        for thread_id in threads:
            seen: dict[str, Any] = {}
            history = list(saver.list({"configurable": {"thread_id": thread_id}}))
            for item in reversed(history):  # oldest first
                for message in item.checkpoint.get("channel_values", {}).get("messages", []) or []:
                    key = str(getattr(message, "id", "") or id(message))
                    if key not in seen and not getattr(message, "additional_kwargs", {}).get("vellum_context_digest"):
                        seen[key] = message
            stream = list(seen.values())
            if len(stream) >= min_messages:
                yield thread_id, stream
        target.close()
        shutil.rmtree(folder, ignore_errors=True)


def summarize(reports: Sequence[ThreadReport], budget: ContextBudget) -> dict[str, Any]:
    calls = sum(r.model_calls for r in reports) or 1
    tool_tokens = sum(r.tool_tokens for r in reports) or 1
    pressures = sorted(p for r in reports for p in r.pressure)

    def pct(q: float) -> float:
        return round(pressures[min(len(pressures) - 1, int(q * len(pressures)))], 3) if pressures else 0.0

    return {
        "threads": len(reports),
        "window": budget.window,
        "input_limit": budget.input_limit,
        "model_calls": sum(r.model_calls for r in reports),
        "compaction_rate": round(sum(r.compactions for r in reports) / calls, 4),
        "exceeded_rate": round(sum(r.exceeded for r in reports) / calls, 4),
        "threads_with_exceeded": sum(1 for r in reports if r.exceeded),
        "window_use_p50": pct(.5), "window_use_p95": pct(.95),
        "tool_results": sum(r.tool_results for r in reports),
        "tool_evidence_removed_share": round(sum(r.tool_tokens_removed for r in reports) / tool_tokens, 4),
    }
