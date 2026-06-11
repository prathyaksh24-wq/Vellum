from fastapi.testclient import TestClient

from agent import api


def test_coding_project_tree_lists_real_files(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "README.md").write_text("# repo", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")

    with TestClient(api.app) as client:
        response = client.get("/api/coding/projects/tree", params={"root": str(tmp_path)})

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert "backend" in names
    assert "README.md" in names
    assert ".env" not in names


def test_coding_project_tree_rejects_missing_root(tmp_path):
    with TestClient(api.app) as client:
        response = client.get("/api/coding/projects/tree", params={"root": str(tmp_path / "missing")})

    assert response.status_code == 404
