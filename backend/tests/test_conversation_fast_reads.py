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


def test_history_is_stored_per_chat_and_only_changed_chats_are_rewritten(tmp_path):
    path = _store(tmp_path)  # starts as the original single-file layout
    lifecycle = ConversationLifecycle(path=path)
    rows = lifecycle.list()
    lifecycle._write(rows)  # first write migrates
    index = json.loads(path.read_text(encoding="utf-8"))
    assert index["storage_version"] == 2
    assert all("messages" not in row and row["message_count"] == 1 for row in index["conversations"])
    assert (tmp_path / "conversations.v1-backup.json").exists()
    files = {item.name: item.stat().st_mtime_ns for item in (tmp_path / "conversations").iterdir()}
    assert set(files) == {"chat_0.json", "chat_1.json", "chat_2.json"}

    rows = lifecycle.list()
    rows[1]["messages"].append({"role": "assistant", "text": "hi"})
    import time
    time.sleep(0.02)
    lifecycle._write(rows)
    after = {item.name: item.stat().st_mtime_ns for item in (tmp_path / "conversations").iterdir()}
    assert after["chat_0.json"] == files["chat_0.json"]
    assert after["chat_2.json"] == files["chat_2.json"]
    assert after["chat_1.json"] != files["chat_1.json"]
    assert ConversationLifecycle(path=path).get("chat_1")["messages"][-1]["text"] == "hi"


def test_deleted_chat_removes_its_message_file(tmp_path):
    path = _store(tmp_path, count=2)
    lifecycle = ConversationLifecycle(path=path)
    lifecycle._write(lifecycle.list())
    lifecycle._write([row for row in lifecycle.list() if row["id"] != "chat_0"])
    assert not (tmp_path / "conversations" / "chat_0.json").exists()
    assert [row["id"] for row in lifecycle.list_view()] == ["chat_1"]


def test_unusual_ids_get_safe_distinct_file_names(tmp_path):
    lifecycle = ConversationLifecycle(path=tmp_path / "conversations.json")
    lifecycle._write([{"id": "Chat", "messages": [{"text": "a"}]}, {"id": "chat", "messages": [{"text": "b"}]},
                      {"id": "../escape", "messages": [{"text": "c"}]}])
    names = sorted(item.name for item in (tmp_path / "conversations").iterdir())
    assert len(names) == 3 and "chat.json" in names
    assert all("/" not in name and ".." not in name for name in names)
    assert [row["messages"][0]["text"] for row in lifecycle.list_view()] == ["a", "b", "c"]


def test_prepare_storage_converts_once_and_keeps_a_backup(tmp_path):
    path = _store(tmp_path)
    lifecycle = ConversationLifecycle(path=path)
    assert lifecycle.prepare_storage() is True
    assert lifecycle.prepare_storage() is False
    assert json.loads(path.read_text(encoding="utf-8"))["storage_version"] == 2
    assert (tmp_path / "conversations.v1-backup.json").exists()
    assert [len(row["messages"]) for row in lifecycle.list_view()] == [1, 1, 1]
