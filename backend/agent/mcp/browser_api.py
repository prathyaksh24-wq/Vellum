"""Read-only view of the canonical Playwright session; mutations are App Actions."""
import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect
from agent.contracts.browser import BrowserFrame, BrowserStatus
from agent.mcp.playwright_tools import browser_session

router = APIRouter(prefix="/browser", tags=["browser"])


@router.get("/status", response_model=BrowserStatus)
def status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return browser_session("status")
    except Exception:
        raise HTTPException(503, "Browser status is unavailable. Retry shortly.") from None


@router.get("/frame", response_model=BrowserFrame)
def frame(response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return browser_session("frame")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        raise HTTPException(503, "Browser view is unavailable. Refresh or reopen the session.") from None


def local_preview_origin(origin: str | None) -> bool:
    """A remote webpage must not read the user's local browser feed."""
    try:
        parsed = urlsplit(origin or "")
        return (parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                and not parsed.username and not parsed.password and parsed.path in {"", "/"}
                and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


@router.websocket("/stream")
async def stream(socket: WebSocket):
    if not local_preview_origin(socket.headers.get("origin")):
        await socket.close(code=1008)
        return
    await socket.accept()
    async def publish():
        previous = None
        while True:
            try:
                next_frame = await asyncio.to_thread(browser_session, "frame")
                if next_frame != previous:
                    await socket.send_json(next_frame.model_dump())
                    previous = next_frame
            except ValueError:
                previous = None
            except Exception:
                await socket.send_json({"error":"The live view disconnected. Reopen the browser session."})
                return
            await asyncio.sleep(.04)
    # Receive solely to observe disconnect promptly, even on an idle page.
    # All input/mutations still enter the canonical App Action path.
    async def disconnected():
        while True:
            await socket.receive_text()
    tasks = {asyncio.create_task(publish()), asyncio.create_task(disconnected())}
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
