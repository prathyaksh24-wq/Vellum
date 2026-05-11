from __future__ import annotations


def test_tui_app_exports_launchable_app() -> None:
    from agent.tui.app import VellumTuiApp

    assert VellumTuiApp.CSS_PATH == "styles.tcss"


def test_stream_chunk_text_handles_langchain_message_chunks() -> None:
    from agent.tui.app import stream_chunk_text

    class Chunk:
        content = [{"type": "text", "text": "patience"}, " and water"]

    assert stream_chunk_text(Chunk()) == "patience and water"


def test_thread_config_uses_supplied_thread_id() -> None:
    from agent.tui.app import thread_config

    assert thread_config("books") == {"configurable": {"thread_id": "books"}}


def test_ledger_summary_reads_audit_log(tmp_path) -> None:
    from agent.tui.screens.ledger import load_usage_summary

    log = tmp_path / "audit_log.jsonl"
    log.write_text(
        "\n".join(
            [
                '{"ts":"2026-05-08T10:00:00+00:00","model":"model-a","prompt_tokens_approx":100,"response_tokens_approx":50}',
                '{"ts":"2026-05-08T11:00:00+00:00","model":"model-b","usage":{"prompt_tokens":20,"completion_tokens":30}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = load_usage_summary(log)

    assert summary.total_tokens == 200
    assert summary.models["model-a"] == 150
    assert summary.models["model-b"] == 50


def test_slash_commands_filter_by_name_and_alias() -> None:
    from agent.tui.slash_commands import filter_commands

    names = [command.name for command in filter_commands("/tok")]

    assert names == ["/tokens"]


def test_slash_commands_resolve_alias() -> None:
    from agent.tui.slash_commands import resolve_command

    command = resolve_command("/usage")

    assert command is not None
    assert command.action == "ledger"
