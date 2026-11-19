"""Replay recorded Vellum threads through the context manager and print numbers.

Usage (repository root):
    .venv\\Scripts\\python.exe scripts\\context_replay.py [--window 32768] [--min-messages 20] [--json out.json]

Reads data/memory/checkpoints.db through a private copy; never writes to it and
never calls a model. The instructions/memory/tool prefix is built once from the
live prompt assembler, so the fixed overhead matches the current configuration.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=None, help="override the main context window")
    parser.add_argument("--output", type=int, default=2048, help="reserved output tokens")
    parser.add_argument("--min-messages", type=int, default=20)
    parser.add_argument("--model", default="ollama/gemma4:12b")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--recover", action="store_true",
                        help="use overflow recovery (fit_context) with --output as the answer floor")
    parser.add_argument("--reasoning-output", type=int, default=None,
                        help="reserve this much output (a reasoning mode); --output stays the answer floor")
    args = parser.parse_args()

    from dataclasses import replace
    from langchain_core.messages import HumanMessage
    from agent.graph import agent as runtime
    from functools import partial
    from agent.llm.context import context_budget, context_layers, fit_context, project_context
    from agent.llm.context_replay import full_message_streams, replay_thread, summarize

    probe = {"messages": [HumanMessage(content="Continue the current task.", id="replay-probe")]}
    prefix = runtime._assemble_vellum_prompt(probe, {"configurable": {"thread_id": "context-replay"}},
                                             runtime_model=args.model)[:-1]
    tools, deferred = runtime._all_runtime_tools()
    config = replace(runtime.load_tool_search_config(), context_length=args.window or 32768)
    visible = runtime.assemble_tool_defs(runtime.to_openai_defs(tools), deferred_names=deferred,
                                         source_labels=runtime._source_labels_for(deferred), config=config).tool_defs
    budget = context_budget(args.model, role="main", output_tokens=args.reasoning_output or args.output)
    project = partial(fit_context, min_output=args.output) if args.recover else project_context
    if args.window:
        budget = replace(budget, window=args.window, margin=max(512, -(-args.window * 5 // 100)))

    reports = [replay_thread(thread_id, stream, prefix, visible, budget, project=project)
               for thread_id, stream in full_message_streams(ROOT / "data" / "memory" / "checkpoints.db",
                                                             min_messages=args.min_messages)]
    result = {"fixed_prefix_layers": project_context(prefix, visible, budget).report["layers"],
              "token_ratio": budget.token_ratio, "recover": args.recover, **summarize(reports, budget)}
    print(json.dumps(result, indent=2))
    if args.json:
        args.json.write_text(json.dumps({"summary": result, "threads": [r.as_dict() for r in reports]}, indent=2),
                             encoding="utf-8")


if __name__ == "__main__":
    main()
