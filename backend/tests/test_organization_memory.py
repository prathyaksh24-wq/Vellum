from pathlib import Path

import pytest

from agent.organization import MemoryBroker, OrganizationStore


def test_private_memory_is_not_discoverable_by_peer(tmp_path: Path) -> None:
    store = OrganizationStore(tmp_path / "organization.db")
    broker = MemoryBroker(store, departments={"SportsAgent": "sports", "XAgent": "social", "VellumAgent": "organization"})
    record = broker.write(actor="SportsAgent", scope="agent:SportsAgent", text="Private tactical preference", confidence=0.9)

    assert broker.search(actor="XAgent", query="tactical") == []
    with pytest.raises(PermissionError, match="memory unavailable"):
        broker.get(actor="XAgent", record_id=record.id)


def test_department_memory_is_shared_only_with_members(tmp_path: Path) -> None:
    store = OrganizationStore(tmp_path / "organization.db")
    broker = MemoryBroker(store, departments={"SportsAgent": "sports", "AnalystAgent": "sports", "XAgent": "social"})
    broker.write(actor="SportsAgent", scope="department:sports", text="Use official standings", confidence=0.8)

    assert broker.search(actor="AnalystAgent", query="standings")[0].text == "Use official standings"
    assert broker.search(actor="XAgent", query="standings") == []


def test_promotion_creates_new_attributed_version(tmp_path: Path) -> None:
    store = OrganizationStore(tmp_path / "organization.db")
    broker = MemoryBroker(store, departments={"SportsAgent": "sports", "VellumAgent": "organization"})
    private = broker.write(actor="SportsAgent", scope="agent:SportsAgent", text="Stable fact", confidence=0.95)

    promoted = broker.promote(actor="VellumAgent", record_id=private.id, target_scope="organization:shared")

    assert promoted.id != private.id
    assert promoted.parent_id == private.id
    assert promoted.owner == "SportsAgent"
    assert store.get(private.id).scope == "agent:SportsAgent"
