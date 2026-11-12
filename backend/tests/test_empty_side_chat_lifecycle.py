from unittest.mock import Mock

from agent.conversations.lifecycle import ConversationLifecycle


def test_empty_temporary_chat_skips_content_effects_but_remains_saved(tmp_path):
    indexer, projector, rename = Mock(return_value={}), Mock(return_value={}), Mock()
    lifecycle = ConversationLifecycle(path=tmp_path / "chats.json", indexer=indexer,
                                      projector=projector, rename_session=rename)
    result = lifecycle.save("side", {"title": "Side chat", "messages": [], "temporary_side_chat": True})
    assert lifecycle.get("side")["temporary_side_chat"] is True
    assert result["changed"] is True
    indexer.assert_not_called()
    projector.assert_not_called()
    rename.assert_not_called()
    lifecycle.save("side", {"title": "Side chat", "temporary_side_chat": True,
                            "messages": [{"id": "one", "role": "user", "text": "Hello"}]})
    indexer.assert_called_once()
    projector.assert_called_once()
