"""Google connection changes use Vellum's existing App Actions."""
from pydantic import ValidationError

from agent.app_actions.models import AppActionDefinition
from agent.contracts.google_workspace import GoogleApiOperation, GoogleSelection
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.google_workspace import google_service


def prepare_google_api(arguments):
    from agent.plugins.google_api import GoogleApiAdapter
    try:
        operation = GoogleApiOperation.model_validate(arguments)
    except ValidationError as exc:
        fields = ', '.join('.'.join(str(part) for part in item['loc']) for item in exc.errors(include_input=False))
        raise ValueError('Correct Google operation fields: '+fields+'. Supply service, method_id and parameters; resource IDs belong inside parameters. No change was applied.') from None
    return GoogleApiAdapter().prepare(operation)


def google_contribution(*, service=None, invalidator=None):
    def execute(payload, operation):
        current = service or google_service()
        try:
            if operation == "api":
                from agent.plugins.google_api import GoogleApiAdapter
                return GoogleApiAdapter(service=current).execute(GoogleApiOperation.model_validate(payload.get("arguments") or {}),
                    binding=payload.get("confirmation_binding"), confirmed=payload.get("confirmed") is True)
            if operation == "configure":
                if payload.get("confirm") is not True:
                    raise ValueError("Use the Google connection controls to select services.")
                result = current.configure(GoogleSelection.model_validate(payload.get("arguments") or {}))
            else:
                if payload.get("confirmed") is not True:
                    raise ValueError("Confirm Google disconnection first.")
                if payload.get("arguments"):
                    raise ValueError("Disconnect does not accept arguments.")
                result = current.disconnect()
            if invalidator:
                invalidator()
            return result
        except ValidationError:
            raise PluginContributionActionError("GOOGLE_CONNECTION_FAILED", "Check the selected Google services and local return address.") from None
        except (ValueError, RuntimeError) as exc:
            raise PluginContributionActionError("GOOGLE_CONNECTION_FAILED", str(exc)) from None

    actions = []
    for operation, title, access, rule in (
        ("configure", "Choose Google services", "external_write", "oauth_consent"),
        ("disconnect", "Disconnect Google", "destructive", "operation_bound"),
    ):
        identifier = "google.connection." + operation
        actions.append(PluginActionContribution(definition=AppActionDefinition(
            id=identifier, version="1", owner="google-workspace", plugin_id="google-workspace", title=title,
            description=title + " for Vellum on this device.", scope="user", access_class=access,
            confirmation_rule=rule, executor_location="server", supports_undo=False, idempotent=False,
            argument_schema=GoogleSelection.model_json_schema() if operation == "configure" else {"type": "object", "additionalProperties": False},
            result_schema={"type": "object"}, ui_reference="google.connection", audit_label=identifier, required_permissions=[identifier]),
            adapter=lambda payload, op=operation: execute(payload, op), allowed_agents=frozenset({"VellumUI"})))
    actions.append(PluginActionContribution(definition=AppActionDefinition(
        id="google.api.execute", version="1", owner="google-workspace", plugin_id="google-workspace",
        title="Change Google data", description="Create, send, update, edit or delete Google data using a published API method and an exact-operation review.",
        scope="user", access_class="external_write", confirmation_rule="operation_bound", executor_location="server",
        supports_undo=False, idempotent=False, argument_schema=GoogleApiOperation.model_json_schema(),
        result_schema={"type":"object"}, ui_reference="google.connection", audit_label="google.api.execute", required_permissions=["google.api.execute"]),
        adapter=lambda payload: execute(payload, "api"), allowed_agents=frozenset({"VellumAgent", "VellumUI"})))
    return PluginContribution(owner="google-workspace", actions=tuple(actions))
