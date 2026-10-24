"""Local UI transport for secret staging; opaque IDs cross the App Action seam."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from agent.account_api import local_client
from agent.contracts.product_hunt import ProductHuntCredential, ProductHuntRead, ProductHuntResult, ProductHuntStatus
from agent.plugins.product_hunt import ProductHuntError, product_hunt_service


def trusted_plugin_view(request: Request, response: Response):
    local_client(request)
    origins = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (4242, 5173, 1420, 8000)}
    if request.headers.get("origin") not in origins or request.headers.get("x-vellum-producthunt") != "1":
        raise HTTPException(403, "Open the Product Hunt connection from the local Vellum app.")
    response.headers["Cache-Control"] = "no-store"


class StagedCredentialResponse(BaseModel):
    credential_id: str
    expires_in: int = 600


class DiscardCredential(BaseModel):
    credential_id: str = Field(min_length=30, max_length=100)


class ProductHuntRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def redacted_validation(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, "Check the Product Hunt credential and request fields.") from None
        return redacted_validation


router = APIRouter(prefix="/plugins/producthunt", tags=["producthunt"], route_class=ProductHuntRoute,
    dependencies=[Depends(trusted_plugin_view)])


@router.get("/status", response_model=ProductHuntStatus)
def status():
    return product_hunt_service().status()


@router.post("/credentials/stage", response_model=StagedCredentialResponse)
def stage(body: ProductHuntCredential):
    try:
        reference = product_hunt_service().stage(body.token.get_secret_value())
        return StagedCredentialResponse(credential_id=reference)
    except ProductHuntError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/credentials/discard")
def discard(body: DiscardCredential):
    product_hunt_service().discard(body.credential_id)
    return {"discarded": True}


@router.post("/read", response_model=ProductHuntResult)
def read(body: ProductHuntRead):
    try:
        return product_hunt_service().read(body)
    except ProductHuntError as exc:
        raise HTTPException(400, str(exc)) from None
