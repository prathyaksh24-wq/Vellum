"""The conversation learner: learns, corrects itself, retries, stops, and heals."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.memory.learner import MAX_ATTEMPTS, ConversationLearner, ModelUnavailable, parse_ops
from agent.memory.orchestrator import SQLiteMemoryStore

OLD = "2026-01-01T00:00:00+00:00"  # long quiet


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def conversation(thread_id, *texts, updated_at=OLD, temporary=False):
    messages = []
    for text in texts:
        messages += [{"role": "user", "text": text}, {"role": "assistant", "text": "ok"}]
    return {"id": thread_id, "thread_id": thread_id, "title": thread_id, "messages": messages,
            "updated_at": updated_at, "temporary": temporary}


def answer(add=(), update=(), retire=()):
    return json.dumps({"add": list(add), "update": list(update), "retire": list(retire)})


@pytest.fixture
def store(tmp_path: Path):
    return SQLiteMemoryStore(tmp_path / "memory.db")


def events(store, name):
    return [e for e in store.audit_log(limit=200) if e["event"] == name]


def test_learns_durable_things_from_a_quiet_conversation(store):
    chats = [conversation("c1", "I'm a nurse on night shifts, so plan anything after 2pm."),
             conversation("busy", "still typing", updated_at=datetime.now(UTC).isoformat()),
             conversation("temp", "I'm vegan", temporary=True)]
    prompts = []

    def model(system, prompt):
        prompts.append(prompt)
        return answer(add=[{"kind": "fact", "text": "Works night shifts as a nurse.", "confidence": 0.9}])

    learner = ConversationLearner(store, lambda: chats, model=model)
    result = learner.run()
    assert result["learned_from"] == 1 and result["added"] == 1
    assert len(prompts) == 1 and "night shifts" in prompts[0]  # the busy and temporary chats were skipped
    assert [m["text"] for m in store.list_saved()] == ["Works night shifts as a nurse."]
    assert len(events(store, "learned")) == 1
    assert learner.run()["learned_from"] == 0  # nothing new: not re-read


def test_corrects_and_retires_what_the_user_contradicted(store):
    wrong = store.add_pending(kind="preference", text="Prefers long detailed answers.", source_thread_id="old",
                              confidence=0.9)
    store.promote(wrong)
    outdated = store.add_pending(kind="project", text="Is building a Flask app.", source_thread_id="old",
                                 confidence=0.9)
    store.promote(outdated)
    pinned = store.add_pending(kind="fact", text="Lives in Pune.", source_thread_id="old", confidence=0.9)
    store.promote(pinned)
    store.pin(pinned, True) if hasattr(store, "pin") else None
    chats = [conversation("c2", "Keep answers short please. I dropped the Flask app.")]
    learner = ConversationLearner(store, lambda: chats, model=lambda s, p: answer(
        update=[{"id": wrong, "text": "Prefers short answers.", "reason": "user asked for short"},
                {"id": 99999, "text": "Made up memory.", "reason": "not shown"}],
        retire=[{"id": outdated, "reason": "dropped the project"}]))
    result = learner.run()
    assert result["corrected"] == 1 and result["retired"] == 1
    assert store.get_memory(wrong)["text"] == "Prefers short answers."
    assert store.get_memory(outdated)["status"] == "archived"
    corrected = events(store, "corrected")[0]["detail"]
    assert "Prefers long detailed answers." in corrected and "Prefers short answers." in corrected


def test_a_malformed_answer_is_corrected_once_before_it_counts(store):
    replies = iter(["Sure! Here are some memories: likes tea", answer(add=[
        {"kind": "preference", "text": "Drinks tea, not coffee.", "confidence": 0.8}])])
    seen = []

    def model(system, prompt):
        seen.append(prompt)
        return next(replies)

    learner = ConversationLearner(store, lambda: [conversation("c3", "I only drink tea")], model=model)
    assert learner.run()["added"] == 1
    assert "previous answer was rejected" in seen[1]


def test_failures_back_off_stop_after_five_and_retry_daily(store):
    clock = Clock()
    broken = {"on": True}

    def model(system, prompt):
        if broken["on"]:
            raise RuntimeError("model returned garbage")
        return answer(add=[{"kind": "fact", "text": "Plays chess on weekends.", "confidence": 0.8}])

    learner = ConversationLearner(store, lambda: [conversation("c4", "I play chess every weekend")],
                                  model=model, clock=clock)
    tries = 0
    for _ in range(12):
        tries += learner.run()["failed"]
        clock.advance(3600)
    assert tries == MAX_ATTEMPTS  # backed off between tries, then stopped
    assert learner.status()["stopped"] == 1

    broken["on"] = False
    clock.advance(86400)  # a stopped conversation gets one try a day
    assert learner.run()["added"] == 1
    assert learner.status()["learned"] == 1


def test_an_unreachable_model_pauses_without_spending_attempts(store):
    def model(system, prompt):
        raise ModelUnavailable("ollama unreachable")

    learner = ConversationLearner(store, lambda: [conversation("c5", "I live by the sea")], model=model)
    for _ in range(10):
        assert learner.run()["paused"] == "ollama unreachable"
    assert learner.status() == {"conversations": 1, "learned": 0, "failed": 0, "stopped": 0, "waiting": 1,
                                "events": {"learned": 0, "corrected": 0, "retired": 0}}


def test_a_conversation_that_grows_is_learned_again_from_its_new_messages(store):
    chats = [conversation("c6", "I'm learning Japanese")]
    prompts = []

    def model(system, prompt):
        prompts.append(prompt)
        return answer()

    learner = ConversationLearner(store, lambda: chats, model=model)
    learner.run()
    chats[0] = conversation("c6", "I'm learning Japanese", "I switched to Korean")
    learner.run()
    assert "I switched to Korean" in prompts[1] and "learning Japanese" not in prompts[1]


def test_parse_ops_rejects_ids_it_was_not_shown_and_bad_text():
    ops = parse_ops(answer(add=[{"kind": "weird", "text": "Likes hiking.", "confidence": 3},
                                {"kind": "fact", "text": "x"}],
                           update=[{"id": 1, "text": "Fixed."}, {"id": 2, "text": "Not shown."}],
                           retire=[{"id": "nope"}]), {1})
    assert ops["add"] == [{"kind": "fact", "text": "Likes hiking.", "confidence": 1.0}]
    assert [u["id"] for u in ops["update"]] == [1] and ops["retire"] == []
    with pytest.raises(ValueError):
        parse_ops("no json here", set())


def test_parse_ops_accepts_plain_sentences_and_odd_shapes():
    ops = parse_ops(json.dumps({"add": ["Prefers dark mode in every app.", 42, None],
                                "update": {"id": 3, "text": "Lives in Pune now."}, "retire": ["nope"]}), {3})
    assert ops["add"] == [{"kind": "fact", "text": "Prefers dark mode in every app.", "confidence": 0.7}]
    assert ops["update"] == [{"id": 3, "reason": "", "text": "Lives in Pune now."}]
    assert ops["retire"] == []


def test_learning_waits_while_the_user_is_chatting(store, monkeypatch):
    from agent import foreground

    calls = []
    learner = ConversationLearner(store, lambda: [conversation("c9", "I like jazz")],
                                  model=lambda s, p: calls.append(1) or answer())
    import time

    monkeypatch.setattr(foreground, "_last_active", time.monotonic())  # the user just sent a message
    assert "chatting" in learner.run()["paused"] and calls == []
    monkeypatch.setattr(foreground, "_last_active", -1e12)  # quiet again
    assert learner.run()["learned_from"] == 1 and calls == [1]
