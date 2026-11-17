"""Identity handshake for the native desktop host."""
from fastapi import APIRouter, Response

from agent.contracts.desktop import DesktopRuntimeIdentity
from agent.desktop_runtime import runtime_identity

router = APIRouter(prefix="/api/desktop", tags=["desktop"])
_identity = runtime_identity()


@router.get("/runtime", response_model=DesktopRuntimeIdentity)
def identity(response: Response) -> DesktopRuntimeIdentity:
    response.headers["Cache-Control"] = "no-store"
    return DesktopRuntimeIdentity(**_identity)


# The API registers how many agent turns are running; the desktop host asks
# before a development restart so it never cuts off a reply in progress.
_active_turns = lambda: 0  # noqa: E731


def set_activity_provider(provider) -> None:
    global _active_turns
    _active_turns = provider


@router.get("/activity")
def activity(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"active_turns": max(0, int(_active_turns()))}
