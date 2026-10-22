"""Regressions exposed by the Q8/full-precision retrieval comparison."""
from types import SimpleNamespace

import pytest

from agent.agents.browser import BrowserAgent
from agent.agents.books import BooksAgent
from agent.conversations.recall import wants_previous_chats
from agent.knowledge.book_materialization import _chunk_blocks
from agent.llm.routing.adapters import OllamaAdapter
from agent.llm.routing.models import FallbackTarget
from agent.llm.reasoning import ReasoningMode
from agent.profiles.catalog import AgentCatalog


def test_book_chunks_fit_several_passages_in_default_evidence_budget():
    blocks = [SimpleNamespace(id=f"b{i}", text="x" * 700) for i in range(12)]
    chunks = _chunk_blocks(blocks)
    assert max(len("\n\n".join(b.text for b in chunk)) for chunk in chunks) <= 1600
    assert [b.id for chunk in chunks for b in chunk] == [b.id for b in blocks]


def test_book_ranking_recovers_exact_terms_outside_dense_candidates():
    from agent.knowledge.book_materialization import _rank_book_hits
    dense = [{"text": "A general introduction.", "score": .9,
              "metadata": {"materialization_id": "m", "chunk_id": "intro"}}]
    exact = {"text": "MY GRANDFATHER VERUS. Character and self-control.", "score": 0,
             "metadata": {"materialization_id": "m", "chunk_id": "answer"}}
    ranked = _rank_book_hits("What did Marcus learn from his grandfather Verus?", dense, [*dense, exact])
    assert any(hit["metadata"]["chunk_id"] == "answer" for hit in ranked[:2])
    assert dense[0]["score"] == .9


def test_book_search_separates_question_from_source_and_presentation_requests():
    from agent.knowledge.book_materialization import _book_search_query
    query = ("In my imported Meditations, what does Marcus say to tell yourself when you struggle to get out of bed? "
             "Use the uploaded book, answer briefly and cite the section.")
    assert _book_search_query(query, ["Meditations"]) == "what does Marcus say to tell yourself when you struggle to get out of bed?"


def test_installed_title_question_reaches_books_even_without_the_word_book():
    class Library:
        def invoke(self, name, payload, **kwargs):
            assert name == "books.skill_lookup"
            return {"books": [{"title": "Meditations"}]}
    books = BooksAgent(tool_registry=Library())
    assert books.can_handle("In my imported Meditations, what does Marcus say about Python decorators?")
    assert not books.can_handle("In my imported budget spreadsheet, what was the revenue?")


@pytest.mark.parametrize("query", [
    "Which web browser have I used before? Use my saved conversations or memory as evidence.",
    "What did we discuss about my calendar in previous chats?",
    "From our saved conversations, which music service do I use?",
    "Which browser have I used before?",
    "Whose latest album did I ask you to play?",
    "What song did I ask you to remove from liked songs?",
])
def test_saved_conversation_questions_do_not_match_action_specialists(tmp_path, query):
    executor = SimpleNamespace(can_handle=lambda query: True)
    catalog = AgentCatalog(profile_dir=tmp_path, executors={"BrowserAgent": executor})
    assert catalog.match(query) is None
    assert wants_previous_chats(query)


@pytest.mark.parametrize("query", [
    "Play the song I mentioned in our previous chat.",
    "What videos have I watched on YouTube?",
    "Show my browser history.",
    "Open the browser and summarize the page.",
    "What events are in my calendar tomorrow?",
])
def test_provider_history_and_new_actions_keep_their_owner(query):
    from agent.conversations.recall import is_conversation_recall
    assert not is_conversation_recall(query)


def test_history_search_ignores_answer_instructions_when_ranking_sources():
    from agent.conversations.recall import recall_history
    conversations = [{"id": "prior", "messages": [
        {"id": "fact", "role": "user", "text": "My browser is Brave."},
        {"id": "noise", "role": "assistant", "text": "Use saved conversations as evidence. Answer briefly; do not guess."},
    ]}]
    result = recall_history(conversations, thread_id="new", scope="previous", limit=1,
        query="Which browser have I used? Use my saved conversations as evidence; answer briefly and do not guess.")
    assert result["messages"][0]["message_id"] == "fact"


def test_misdirected_browser_recall_never_opens_a_browser():
    class NoBrowser:
        def invoke(self, *args, **kwargs):
            pytest.fail("Historical recall must not invoke browser tools")
    browser = BrowserAgent(tool_registry=NoBrowser())
    query = "Which browser have I used before? Use my saved conversations as evidence."
    assert not browser.can_handle(query)
    assert browser.answer(query).status == "needs_fetch"


@pytest.mark.parametrize("mode,expected", [(None, False), (ReasoningMode.high, True)])
def test_thinking_capability_does_not_force_reasoning_on_standard_turns(mode, expected):
    model = OllamaAdapter(base_url="http://127.0.0.1:11434").build_model(
        target=FallbackTarget(provider="ollama", model="ollama/gemma4:12b"),
        secret="", temperature=0, thinking_capable=True, reasoning_mode=mode,
    )
    assert model._chat_params([])["think"] is expected
