"""Memory learns facts about the user, not prompt scaffolding or one-off requests."""

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent import api
from agent.app_actions.models import AppActionContext
from agent.app_actions.settings_runtime import SettingsRuntimeActionError
from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore, _extract_candidates, _memory_topic
from agent.memory.quality import is_one_off_request, is_scaffold, junk_reason, user_words
from agent.memory.resolved import ResolvedQuestionsCache
from agent.tools.capabilities.memory_service import MemoryCapabilityService

ATTACHMENT = ("\n\n[Attachment context] The user attached file(s) in the Vellum UI. If image bytes are "
              "unavailable to the backend, say that visual analysis is not wired yet instead of saying no "
              "image was attached. [1] Zomato (reference, unknown size)")
FOLLOW_UP = ("\n\n[Conversation follow-up context] The current message is a short reaction to the previous "
             "turn. Continue that turn instead of greeting the user or changing topics. Previous user request: "
             "what about now? Previous assistant response: I prefer to keep answers short.")
UI_MODE = ("[Vellum UI mode: Web search is enabled for this turn. Use web_search for public/current facts "
           "before answering.] ")

# Shapes taken from a real store: what old builds saved as "memories".
SAMPLE_CONVERSATION = [
    "@Linear what is my latest issue?" + ATTACHMENT,
    "@imagegen a dog chasing cat" + ATTACHMENT,
    "??" + FOLLOW_UP,
    UI_MODE + "Find the official Python asyncio documentation and summarize it in two sentences.",
    "get me my vellum repo on github",
    "create an issue on linear on new plugin page for vellum",
    "on new channel just say like hi this is vellum",
    "no get out of calendar agent and use the @imagegen skill to create an image" + ATTACHMENT,
    "i like the hybrid approach but for now we'll go with option a",
    "I'd like to create a new automation — a scheduled reasoning task that Vellum runs on its own. "
    "Task idea: plan a weekly meal plan around my schedule.",
    "add that skill to vellum not finding skills",
    "Accumulate recent YouTube watch-history entries locally from Vellum's browser profile. " * 6,
    # Durable things the user actually said.
    "i want to add deepseek creator mode to vellum" + ATTACHMENT,
    "I prefer short answers without headings." + ATTACHMENT,
    "my name is Sam",
    "From now on, always cite the book chapter when you quote it.",
]


@pytest.fixture
def orchestrator(tmp_path: Path, monkeypatch) -> MemoryOrchestrator:
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(sessions_db=tmp_path / "sessions.db"),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory-files",
        provider_extensions=None,
    )
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)
    return orchestrator


def test_user_words_strips_appended_blocks_and_ui_annotations():
    assert user_words("I prefer tea." + ATTACHMENT) == "I prefer tea."
    assert user_words("??" + FOLLOW_UP) == "??"
    assert user_words(UI_MODE + "Find the docs.") == "Find the docs."
    # Stored memory text has its newlines collapsed; the block must still go.
    assert user_words("I prefer tea. [Attachment context] The user attached file(s)") == "I prefer tea."
    assert is_scaffold("@GitHub latest PRs [Attachment context] The user attached file(s)")
    assert not is_scaffold("I prefer tea.")


def test_user_words_stays_linear_on_adversarial_text():
    # CodeQL: long runs of spaces, and many unclosed UI annotations, made the old
    # patterns backtrack quadratically on user-controlled text.
    import time

    spaces = "a" + " " * 50_000 + "b"
    unclosed = "[vellum ui mode:" * 5_000
    started = time.perf_counter()
    assert user_words(spaces) == "a b"
    assert user_words(unclosed) == unclosed
    assert user_words("[Vellum UI mode: plan] I prefer tea.") == "I prefer tea."
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("text", [
    "get me my vellum repo on github",
    "@Linear what is my latest issue",
    "@Swiggy & Instamart order burger from burgerking",
    "can u summarize my merged PRs this week",
    "please schedule a meeting tomorrow at 3pm",
    "on new channel just say like hi this is vellum",
    "i like the hybrid approach but for now we'll go with option a",
    "change the tone of vellum to warm",
    "add that skill to vellum not finding skills",
])
def test_one_off_requests_are_not_memories(text):
    assert is_one_off_request(text)
    assert _extract_candidates(text) == []


@pytest.mark.parametrize("text", [
    "I prefer short answers without headings.",
    "From now on, always use bullet points for lists.",
    "Never use emojis in replies.",
    "I'm building a local-first desktop agent called Vellum.",
    "my name is Sam",
])
def test_durable_statements_are_not_requests(text):
    assert not is_one_off_request(text)
    assert _extract_candidates(text)


def test_extraction_reads_only_the_users_words():
    candidates = _extract_candidates("I prefer short answers without headings." + ATTACHMENT)
    assert [item["text"] for item in candidates] == ["I prefer short answers without headings."]
    assert candidates[0]["kind"] == "preference"
    # The follow-up block quotes an assistant reply with "I prefer ..." in it.
    assert _extract_candidates("??" + FOLLOW_UP) == []
    # Mentioning "Vellum" inside the attachment block no longer makes a project.
    assert _extract_candidates("@GitHub what is my latest PRs" + ATTACHMENT) == []


def test_extraction_keeps_facts_projects_corrections_and_explicit_memories():
    by_text = lambda text: {(c["kind"], c["text"]) for c in _extract_candidates(text)}  # noqa: E731
    assert by_text("i want to add deepseek creator mode to vellum") == {
        ("project", "i want to add deepseek creator mode to vellum.")}
    assert by_text("my name is Sam") == {("fact", "my name is Sam.")}
    assert ("correction", "Check whether the tool actually succeeded before saying it is done.") in by_text(
        "You got that wrong again. Check whether the tool actually succeeded before saying it is done.")
    assert ("fact", "I use VS Code on Windows.") in by_text("Remember that I use VS Code on Windows.")


def test_assistant_text_is_never_learned(orchestrator):
    stored = orchestrator.extract_memory_candidates(
        thread_id="t", user_message="thanks", assistant_message="I prefer short answers. My name is Vellum.")
    assert stored == []


def test_record_turn_sends_only_the_users_words_to_history_and_providers(orchestrator):
    seen: list[str] = []

    class Provider:
        def sync_turn(self, query, answer, **kwargs):
            seen.append(query)
            return []

    orchestrator.provider_extensions = Provider()
    orchestrator.record_turn(thread_id="t", query="I prefer tea." + ATTACHMENT, answer="Noted.",
                             external_query="I prefer tea." + ATTACHMENT)
    assert seen == ["I prefer tea."]
    assert not any("Attachment context" in hit.get("content", "") for hit in orchestrator.fts5.search("tea"))


def test_topics_come_from_the_users_words():
    assert _memory_topic("project", "@GitHub what is my latest PRs" + ATTACHMENT) != "Vellum"
    assert _memory_topic("project", "i want to add deepseek creator mode to vellum") == "Vellum"
    assert _memory_topic("preference", "Keep the tone of Vellum warm.") == "How to talk to me"
    assert _memory_topic("fact", "my name is Sam") == "About you"


def _seed(store: SQLiteMemoryStore) -> dict[str, int]:
    def save(text, **meta):
        memory_id = store._insert_memory(scope="global", kind=meta.pop("kind", "project"), text=text,
                                         status="saved", source_thread_id=meta.pop("thread", "t"),
                                         confidence=0.7, **meta)
        return memory_id
    return {
        "scaffold": save("@Linear what is latest issue [Attachment context] The user attached file(s) in the "
                         "Vellum UI.", topic="Vellum"),
        "follow_up": save("?? [Conversation follow-up context] The current message is a short reaction."),
        "request": save("get me my vellum repo on github."),
        "real": save("i want to add deepseek creator mode to vellum."),
        "manual": save("Get a haircut every six weeks.", kind="manual", thread="manual", origin="stated"),
        "correction": save("Check the tool result before saying it is done.", kind="correction"),
    }


def test_cleanup_previews_then_archives_junk_and_undo_restores_it(orchestrator):
    store = orchestrator.store
    ids = _seed(store)
    context = AppActionContext(source="ui")
    run = api._settings_runtime_actions.execute

    preview = run("memory.cleanup.preview", {}, context)
    assert preview["archived"] == 3 and preview["by_reason"] == {"scaffold": 2, "request": 1}
    assert len(store.list_saved()) == 6  # preview changes nothing

    with pytest.raises(SettingsRuntimeActionError) as raised:
        run("memory.cleanup.run", {}, context)
    assert raised.value.code == "CONFIRMATION_REQUIRED"
    with pytest.raises(HTTPException) as http:
        api._memory_action("memory.cleanup.run", {})
    assert http.value.status_code == 428

    applied = run("memory.cleanup.run", {}, context, confirmed=True)
    assert applied["archived"] == 3
    saved = {item["id"] for item in store.list_saved()}
    assert saved == {ids["real"], ids["manual"], ids["correction"]}
    assert all(store.get_memory(ids[key])["status"] == "archived" for key in ("scaffold", "follow_up", "request"))
    topics = asyncio.run(api.memory_topics())["topics"]
    texts = [entry["text"] for card in topics for entry in card["items"]]
    assert not any("Attachment context" in text or "github" in text for text in texts)

    undone = run("memory.cleanup.run", {"undo": True}, context, confirmed=True)
    assert undone["restored"] == 3
    assert len(store.list_saved()) == 6


def test_dreaming_over_sample_conversation_creates_no_scaffold_memories(orchestrator):
    store = orchestrator.store
    # A scaffold item an old build left pending must not be promoted either.
    store.add_pending(kind="project", text="?/ [Conversation follow-up context] The current message is a reaction.",
                      source_thread_id="old", confidence=0.7)
    for message in SAMPLE_CONVERSATION:
        orchestrator.extract_memory_candidates(thread_id="sample", user_message=message,
                                               assistant_message="Sure, here is what I found in the Vellum UI.")
    result = orchestrator.run_dreaming()

    saved = store.list_saved()
    assert not any(is_scaffold(item["text"]) or junk_reason(item) for item in saved)
    assert not any(is_scaffold(item["text"]) for item in result["new_memories"])
    assert store.list_pending() == []
    assert {item["text"] for item in saved} == {
        "i want to add deepseek creator mode to vellum.",
        "I prefer short answers without headings.",
        "my name is Sam.",
        "From now on, always cite the book chapter when you quote it.",
    }
