"""Pictures of the page after agent browser steps, shown on chat steps."""
import asyncio
import base64
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.mcp import browser_api
from agent.mcp.dedicated_browser import DedicatedBrowser

JPEG = b"\xff\xd8\xff\xe0fixture\xff\xd9"


class FakePage:
    def __init__(self, url="https://www.youtube.com/watch?v=x"):
        self.url = url

    def is_closed(self):
        return False

    async def title(self):
        return "A video - YouTube"


class FakeBridge:
    def __init__(self):
        self.calls = []

    async def call(self, operation, **arguments):
        self.calls.append((operation, arguments))
        return {"preview": "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()}


class FakeContext:
    def target_for_page(self, page):
        return "target-1"


def owner(tmp_path, page):
    browser = DedicatedBrowser.__new__(DedicatedBrowser)
    browser.active_page = page
    browser._native = FakeBridge()
    browser.context = FakeContext()
    browser._storage_path = lambda path: tmp_path / path
    return browser


def test_native_step_preview_saves_a_picture_with_the_page_address(tmp_path):
    browser = owner(tmp_path, FakePage())
    preview = asyncio.run(browser.step_preview())
    assert preview["url"] == "https://www.youtube.com/watch?v=x"
    assert preview["title"] == "A video - YouTube"
    assert preview["image"] == f"/api/browser/step-previews/{preview['id']}.jpg"
    saved = tmp_path / "data/browser-session/step-previews" / f"{preview['id']}.jpg"
    assert saved.read_bytes() == JPEG
    assert browser._native.calls == [("preview", {"target_id": "target-1"})]


def test_step_preview_skips_pages_that_are_not_websites(tmp_path):
    assert asyncio.run(owner(tmp_path, FakePage("about:blank")).step_preview()) is None
    assert asyncio.run(owner(tmp_path, None).step_preview()) is None


def test_step_previews_keep_only_the_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(DedicatedBrowser, "STEP_PREVIEW_LIMIT", 2)
    browser = owner(tmp_path, FakePage())
    for _ in range(4):
        asyncio.run(browser.step_preview())
    assert len(list((tmp_path / "data/browser-session/step-previews").glob("*.jpg"))) == 2


def test_step_preview_route_serves_only_saved_pictures(tmp_path, monkeypatch):
    import agent.config
    monkeypatch.setattr(agent.config, "_resolve_against_repo", lambda path: tmp_path / path)
    folder = tmp_path / "data/browser-session/step-previews"
    folder.mkdir(parents=True)
    name = "a" * 32 + ".jpg"
    (folder / name).write_bytes(JPEG)
    app = FastAPI()
    app.include_router(browser_api.router, prefix="/api")
    client = TestClient(app)
    response = client.get(f"/api/browser/step-previews/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == JPEG
    for bad in ["b" * 32 + ".jpg", "..%2Fsecret.jpg", "a" * 31 + ".jpg", "a" * 32 + ".png"]:
        assert client.get(f"/api/browser/step-previews/{bad}").status_code == 404


def test_only_browser_tools_capture_a_step_preview(monkeypatch):
    from agent import api
    import agent.mcp.playwright_tools as tools
    calls = []
    monkeypatch.setattr(tools, "browser_session", lambda operation: calls.append(operation) or {"image": "/x.jpg"})
    assert asyncio.run(api._browser_step_preview("web_search")) is None
    assert asyncio.run(api._browser_step_preview("browser_navigate")) == {"image": "/x.jpg"}
    assert calls == ["step_preview"]
