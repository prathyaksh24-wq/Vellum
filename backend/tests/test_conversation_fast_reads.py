import json

from agent.conversations.lifecycle import ConversationLifecycle


def _store(tmp_path, count=3):
    path = tmp_path / "conversations.json"
    rows = [{"id": f"chat_{i}", "thread_id": f"chat_{i}", "title": f"Chat {i}", "revision": 1,
             "messages": [{"role": "user", "text": f"hello {i}"}]} for i in range(count)]
    path.write_text(json.dumps({"conversations": rows}), encoding="utf-8")
    return path


def test_list_view_reads_without_copying_every_message(tmp_path):
    lifecycle = ConversationLifecycle(path=_store(tmp_path))
    first, second = lifecycle.list_view(), lifecycle.list_view()
    assert [row["id"] for row in first] == ["chat_0", "chat_1", "chat_2"]
    # Rows share message data with the read cache instead of deep-copying it.
    assert first[0]["messages"] is second[0]["messages"]
    assert first[0] is not second[0]


def test_list_still_returns_private_copies_for_mutation(tmp_path):
    lifecycle = ConversationLifecycle(path=_store(tmp_path))
    rows = lifecycle.list()
    rows[0]["messages"].append({"role": "assistant", "text": "changed"})
    assert len(lifecycle.list_view()[0]["messages"]) == 1


def test_get_returns_one_private_conversation(tmp_path):
    lifecycle = ConversationLifecycle(path=_store(tmp_path))
    conversation = lifecycle.get("chat_1")
    conversation["messages"].clear()
    assert lifecycle.get("chat_1")["messages"] == [{"role": "user", "text": "hello 1"}]


def test_list_view_sees_new_writes(tmp_path):
    path = _store(tmp_path, count=1)
    lifecycle = ConversationLifecycle(path=path)
    assert len(lifecycle.list_view()) == 1
    path.write_text(json.dumps({"conversations": [{"id": "a"}, {"id": "b"}]}), encoding="utf-8")
    assert [row["id"] for row in lifecycle.list_view()] == ["a", "b"]
