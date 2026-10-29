"""Product Hunt connection mutations use the existing App Action owner."""
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.app_actions.models import AppActionDefinition
from agent.contracts.product_hunt import PLUGIN_ID, ProductHuntFollow
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.product_hunt import ProductHuntError, product_hunt_service


class StagedCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential_id: str = Field(min_length=30, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


FOLLOW_ACTIONS = {"producthunt.user.follow", "producthunt.user.unfollow"}


def prepare_product_hunt_follow(action_id, arguments):
    try:
        request = ProductHuntFollow.model_validate(arguments)
        return product_hunt_service().prepare_follow(request.username, following=action_id.endswith(".follow"))
    except ValidationError:
        raise ProductHuntError("Enter one exact Product Hunt username to review.") from None


def product_hunt_contribution(*, service=None):
    def execute(payload, action):
        try:
            current = service or product_hunt_service()
            if action == "connect":
                if payload.get("confirmed") is not True:
                    raise ProductHuntError("Confirm connecting Product Hunt first.")
                credential = StagedCredential.model_validate(payload.get("arguments") or {})
                status = current.connect(credential.credential_id)
            elif action == "disconnect":
                if payload.get("confirmed") is not True:
                    raise ProductHuntError("Confirm disconnecting Product Hunt first.")
                status = current.disconnect()
            else:
                status = current.verify()
            return {"changed": True, "connection": status.model_dump(), "_message": status.message}
        except ValidationError:
            raise PluginContributionActionError("INVALID_ACTION_ARGUMENTS", "Enter the Product Hunt credential through its connection form.") from None
        except ProductHuntError as exc:
            raise PluginContributionActionError("PRODUCT_HUNT_CONNECTION_FAILED", str(exc)) from None

    def change_follow(payload, *, following):
        try:
            current = service or product_hunt_service()
            request = ProductHuntFollow.model_validate(payload.get("arguments") or {})
            return current.set_following(request, following=following,
                binding=payload.get("confirmation_binding"), confirmed=payload.get("confirmed") is True)
        except ValidationError:
            raise PluginContributionActionError("INVALID_ACTION_ARGUMENTS", "Enter one exact Product Hunt username.") from None
        except ProductHuntError as exc:
            raise PluginContributionActionError("PRODUCT_HUNT_CHANGE_FAILED", str(exc)) from None

    actions = []
    for operation, title, access, confirmation in (
        ("connect", "Connect Product Hunt", "external_write", "operation_bound"),
        ("verify", "Verify Product Hunt connection", "read", "none"),
        ("disconnect", "Disconnect Product Hunt", "destructive", "operation_bound"),
    ):
        action_id = "producthunt.connection." + operation
        actions.append(PluginActionContribution(
            definition=AppActionDefinition(id=action_id, version="1", owner=PLUGIN_ID, plugin_id=PLUGIN_ID,
                title=title, description="Verify public API access with a locally entered credential." if operation == "connect" else title + ".",
                scope="user", access_class=access, confirmation_rule=confirmation, executor_location="server",
                supports_undo=False, idempotent=False, ui_reference="producthunt.connection", audit_label=action_id,
                argument_schema=StagedCredential.model_json_schema() if operation == "connect" else {"type":"object", "additionalProperties":False},
                result_schema={"type":"object", "required":["changed", "connection"]}, required_permissions=[action_id]),
            adapter=lambda payload, op=operation: execute(payload, op),
            # Credential references and disconnect controls never enter model tools.
            allowed_agents=frozenset({"VellumUI"}),
        ))
    for following in (True, False):
        action_id = "producthunt.user." + ("follow" if following else "unfollow")
        actions.append(PluginActionContribution(
            definition=AppActionDefinition(id=action_id, version="1", owner=PLUGIN_ID, plugin_id=PLUGIN_ID,
                title="Follow a Product Hunt user" if following else "Unfollow a Product Hunt user",
                description="Change the authenticated Product Hunt account's following list after exact-user confirmation. Product Hunt must grant Write permission.",
                scope="user", access_class="external_write", confirmation_rule="operation_bound", executor_location="server",
                supports_undo=False, idempotent=False, ui_reference="producthunt.connection", audit_label=action_id,
                argument_schema=ProductHuntFollow.model_json_schema(), result_schema={"type":"object", "required":["changed", "user", "following"]},
                required_permissions=[action_id]),
            adapter=lambda payload, value=following: change_follow(payload, following=value),
        ))
    return PluginContribution(owner=PLUGIN_ID, actions=tuple(actions))
