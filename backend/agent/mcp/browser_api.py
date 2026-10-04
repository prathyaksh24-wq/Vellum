"""Read-only view of the canonical Playwright session; mutations are App Actions."""
from fastapi import APIRouter, HTTPException, Response
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
