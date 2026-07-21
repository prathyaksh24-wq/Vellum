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
    assert "closeSession:(id,discardChanges=false)" in html
    assert "sessionProjectRoot(session)" in html
    assert "checkpoint:(id,checkpointId)" in html
    assert "Checkpoint captured" in html
    assert "rewindCodingCheckpoint" in html
    assert "provider will start with a fresh session" in html
    assert "supportedAccessModeIds" in html
    assert 'item.id!=="ask_every_time"||codingProvider==="claude"' not in html
    assert "PLANNER_SYS" not in html
    assert "async function streamModel" not in html
    assert "? <ChromeBrowser" not in html


def test_workspace_html_exposes_real_project_files_without_secret_preview() -> None:
    html = WORKSPACE_HTML.read_text(encoding="utf-8")

    assert "/api/coding/projects/file" in html
    assert "projectFile(codingSession.cwd,path)" in html
    assert "Preview of the selected file would render here" not in html
    assert "prathyaksh24@gmail.com" not in html


def test_workspace_html_exposes_functional_studio_composer() -> None:
    html = WORKSPACE_HTML.read_text(encoding="utf-8")

    assert 'className="input-wrap studio-composer"' in html
    assert "Agent runtime" in html
    assert "Queue a follow-up while the agent works" in html
    assert "window.SpeechRecognition||window.webkitSpeechRecognition" in html
    assert 'aria-label="Send prompt"' in html
    assert "setQueued(prev=>[...prev" in html
    assert "attachmentBudget=131072" in html
    assert "content=await f.text()" in html
