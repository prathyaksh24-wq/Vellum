from pathlib import Path


WORKSPACE_HTML = (
    Path(__file__).resolve().parents[2]
    / "design"
    / "Velllum"
    / "uploads"
    / "vellum-workspace.html"
)


def test_workspace_html_uses_web_native_coding_runtime() -> None:
    html = WORKSPACE_HTML.read_text(encoding="utf-8")

    assert "<title>Vellum Workspace</title>" in html
    assert '<VellumWorkspace shell="web"' in html
    assert "createCodingApi" in html
    assert "/api/coding/sessions/" in html
    assert 'codingApiRef.current.stop(session.id)' in html
    assert "PLANNER_SYS" not in html
    assert "async function streamModel" not in html
    assert "? <ChromeBrowser" not in html


def test_workspace_html_exposes_real_project_files_without_secret_preview() -> None:
    html = WORKSPACE_HTML.read_text(encoding="utf-8")

    assert "/api/coding/projects/file" in html
    assert "projectFile(codingSession.cwd,path)" in html
    assert "Preview of the selected file would render here" not in html
    assert "prathyaksh24@gmail.com" not in html
