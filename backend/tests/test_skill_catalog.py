import sqlite3
import json
from pathlib import Path

import pytest

from agent.skills import SkillCatalog, SkillCatalogError, SkillTextNormalizer, calibrate_semantic_threshold


def write_skill(root: Path, name: str, description: str, procedure: str) -> None:
    package = root / "packages" / "tests" / name
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n\n## When to Use\nUse for {description}.\n\n## Procedure\n{procedure}\n",
        encoding="utf-8",
    )


def test_catalog_reconciles_searches_and_reuses_semantic_fingerprint(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    write_skill(root, "deploy-safe", "safe deployments", "Verify then deploy.")
    calls = []

    def embed(text: str) -> list[float]:
        calls.append(text)
        return [1.0, 0.0]

    catalog = SkillCatalog(root, db_path=tmp_path / "catalog.db", embedder=embed)
    first = catalog.reconcile()
    second = catalog.reconcile()

    assert first.recomputed_embeddings == 1
    assert second.unchanged_embeddings == 1
    assert len(calls) == 1
    assert catalog.search("deploy")[0]["normalized_name"] == "deploy-safe"
    with sqlite3.connect(tmp_path / "catalog.db") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_skill_event_ledger_is_immutable_filterable_and_idempotent(tmp_path: Path) -> None:
    catalog = SkillCatalog(tmp_path / ".skills", db_path=tmp_path / "catalog.db")

    first = catalog.record_event(
        "install",
        "webapp-testing",
        details={"source": "skills-sh"},
        event_key="install:webapp-testing:1",
        created_at="2026-07-14T03:00:00+00:00",
    )
    repeated = catalog.record_event(
        "install",
        "webapp-testing",
        details={"source": "skills-sh"},
        event_key="install:webapp-testing:1",
        created_at="2026-07-14T03:00:00+00:00",
    )

    events = catalog.events(
        since="2026-07-14T00:00:00+00:00",
        until="2026-07-15T00:00:00+00:00",
        event="install",
    )
    assert first["id"] == repeated["id"]
    assert len(events) == 1
    assert events[0]["skill_name"] == "webapp-testing"
    assert events[0]["details"]["source"] == "skills-sh"


def test_backfill_does_not_duplicate_an_event_already_written_live(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    audit = root / ".hub" / "audit.log"
    audit.parent.mkdir(parents=True)
    record = {"timestamp": "2026-07-14T03:00:00+00:00", "action": "install", "name": "ontology", "source": "hub", "outcome": "ok"}
    audit.write_text(json.dumps(record) + "\n", encoding="utf-8")
    catalog = SkillCatalog(root, db_path=tmp_path / "catalog.db")
    catalog.record_event("install", "ontology", event_key="hub:install:ontology:2026-07-14T03:00:00+00:00", created_at=record["timestamp"])

    catalog.backfill_events()

    assert len(catalog.events(event="install", skill_name="ontology")) == 1


def test_catalog_rejects_exact_content_duplicate_and_obfuscated_identity(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    write_skill(root, "one", "same", "same")
    first = root / "packages" / "tests" / "one"
    second = root / "retired" / "tests" / "two"
    second.parent.mkdir(parents=True)
    second.mkdir()
    (second / "SKILL.md").write_bytes((first / "SKILL.md").read_bytes())

    with pytest.raises(SkillCatalogError, match="duplicate normalized skill name"):
        SkillCatalog(root, db_path=tmp_path / "catalog.db", embedder=lambda _text: [1.0]).reconcile()
    assert SkillTextNormalizer.identity("Ｄｅｐｌｏｙ\u200b Skill") == "deploy skill"
    with pytest.raises(SkillCatalogError, match="bidirectional"):
        SkillTextNormalizer.normalize("safe\u202eevil")


def test_semantic_candidates_require_persisted_decision(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    write_skill(root, "alpha", "deployment alpha", "Deploy alpha.")
    write_skill(root, "beta", "deployment beta", "Deploy beta.")
    catalog = SkillCatalog(root, db_path=tmp_path / "catalog.db", embedder=lambda _text: [1.0, 0.0])

    report = catalog.reconcile()
    review = catalog.duplicate_reviews()[0]

    assert report.duplicate_candidates == 1
    with pytest.raises(SkillCatalogError, match="require a reason"):
        catalog.decide_duplicate(review["id"], "distinct")
    decided = catalog.decide_duplicate(review["id"], "distinct", distinct_reason="Different production targets")
    assert decided["status"] == "distinct"


def test_semantic_threshold_calibrates_on_200_labeled_cases() -> None:
    cases = [(0.99, True)] * 50 + [(0.95, True)] * 50 + [(0.70, False)] * 50 + [(0.10, False)] * 50
    result = calibrate_semantic_threshold(cases)

    assert result["cases"] == 200
    assert result["precision"] >= 0.95
    assert result["recall"] >= 0.85
