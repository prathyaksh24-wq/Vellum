import json

from agent.skills import SkillUsageStore


def test_usage_store_tracks_creation_origin_and_counters(tmp_path) -> None:
    store = SkillUsageStore(tmp_path)

    store.mark_created("foreground", origin="foreground")
    store.mark_created("background", origin="background_review")
    store.increment_view("foreground")
    store.increment_use("foreground")
    store.increment_patch("foreground")

    assert store.get("foreground")["created_by"] is None
    assert store.get("foreground")["view_count"] == 1
    assert store.get("foreground")["use_count"] == 1
    assert store.get("foreground")["patch_count"] == 1
    assert store.get("background")["created_by"] == "agent"
    assert json.loads((tmp_path / ".usage.json").read_text(encoding="utf-8"))


def test_usage_store_missing_sidecar_is_empty_and_state_is_persisted(tmp_path) -> None:
    store = SkillUsageStore(tmp_path)

    assert store.all() == {}

    store.set_state("skill-a", "archived")

    assert store.get("skill-a")["state"] == "archived"
    assert store.get("skill-a")["archived_at"] is not None


def test_usage_store_pins_and_unpins_skill(tmp_path) -> None:
    store = SkillUsageStore(tmp_path)
    store.mark_created("skill-a", origin="background_review")

    store.pin("skill-a")
    assert store.get("skill-a")["pinned"] is True

    store.unpin("skill-a")
    assert store.get("skill-a")["pinned"] is False
