from fastapi.testclient import TestClient

from agent import api


def test_coding_project_tree_lists_real_files(monkeypatch, tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "README.md").write_text("# repo", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / ".env.development").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / ".npmrc").write_text("//registry.npmjs.org/:_authToken=x", encoding="utf-8")
    (tmp_path / "id_rsa").write_text("PRIVATE KEY", encoding="utf-8")
    monkeypatch.setattr(api, "_coding_project_roots", lambda: [tmp_path.resolve()])

    with TestClient(api.app) as client:
        response = client.get("/api/coding/projects/tree", params={"root": str(tmp_path)})

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert "backend" in names
    assert "README.md" in names
    assert ".env" not in names
    assert ".env.development" not in names
    assert ".npmrc" not in names
    assert "id_rsa" not in names


def test_coding_project_tree_rejects_missing_root(tmp_path):
    with TestClient(api.app) as client:
        response = client.get("/api/coding/projects/tree", params={"root": str(tmp_path / "missing")})

    assert response.status_code == 404


def test_coding_project_tree_rejects_root_outside_allowed_projects(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setattr(api, "_coding_project_roots", lambda: [allowed.resolve()])

    with TestClient(api.app) as client:
        response = client.get("/api/coding/projects/tree", params={"root": str(outside)})

    assert response.status_code == 403
