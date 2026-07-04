import pytest
from pydantic import ValidationError

from agent.runtime.protocol import MESSAGE_TYPES, parse_message, validate_envelope


@pytest.mark.parametrize("message_type", sorted(MESSAGE_TYPES))
def test_protocol_accepts_all_version_one_message_types(message_type):
    message = parse_message({"version": 1, "type": message_type, "run_id": "r1", "task_id": "t1", "payload": {}})
    assert message.type == message_type


def test_protocol_rejects_unknown_versions_fields_and_identity_mismatch():
    with pytest.raises(ValidationError):
        parse_message({"version": 2, "type": "run", "run_id": "r", "task_id": "t", "payload": {}})
    with pytest.raises(ValidationError):
        parse_message({"version": 1, "type": "run", "run_id": "r", "task_id": "t", "payload": {}, "extra": True})
    message = parse_message({"version": 1, "type": "result", "run_id": "other", "task_id": "t", "payload": {}})
    with pytest.raises(ValueError, match="message identity mismatch"):
        validate_envelope(message, run_id="r", task_id="t")


def test_protocol_rejects_unknown_message_type():
    with pytest.raises(ValidationError):
        parse_message({"version": 1, "type": "execute_anything", "run_id": "r", "task_id": "t", "payload": {}})
