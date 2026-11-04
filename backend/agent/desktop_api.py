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
