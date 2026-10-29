"""Credential changes use the same staged-key/App Action boundary as SerpAPI."""
from agent.app_actions.models import AppActionDefinition
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.keyed_mcp import keyed_mcp_service, KeyedMcpError, PROVIDERS

def keyed_mcp_contribution(provider):
    if provider not in PROVIDERS:
        raise ValueError('Unknown connector')
    def execute(payload, operation):
        service = keyed_mcp_service(provider)
        args = payload.get('arguments') or {}
        try:
            if operation == 'connect':
                if set(args) != {'credential_id'}:
                    raise KeyedMcpError('Choose a staged key from the local connection form.')
                status = service.connect(args['credential_id'])
            else:
                if args:
                    raise KeyedMcpError('This connection action accepts no arguments.')
                if operation == 'disconnect' and payload.get('confirmed') is not True:
                    raise KeyedMcpError('Confirm disconnection first.')
                status = getattr(service, operation)()
            return {'changed': operation != 'verify', 'connection': status.model_dump(), '_message': status.message}
        except KeyedMcpError as exc:
            raise PluginContributionActionError('MCP_CONNECTION_FAILED', str(exc)) from None
    actions = []
    for operation, access, confirmation in (
        ('connect', 'write', 'none'), ('use_configured', 'write', 'none'),
        ('verify', 'read', 'none'), ('disconnect', 'destructive', 'operation_bound')):
        schema = {'type': 'object', 'additionalProperties': False}
        if operation == 'connect':
            schema.update(properties={'credential_id': {'type': 'string', 'minLength': 30, 'maxLength': 100}}, required=['credential_id'])
        action_id = provider + '.connection.' + operation
        actions.append(PluginActionContribution(definition=AppActionDefinition(
            id=action_id, version='1', owner=provider, plugin_id=provider,
            title=operation.replace('_', ' ').capitalize() + ' ' + PROVIDERS[provider][0],
            description='Manage this device’s official MCP connection.', scope='user', access_class=access,
            confirmation_rule=confirmation, executor_location='server', supports_undo=False,
            idempotent=False, ui_reference='plugin-manage', audit_label=action_id,
            argument_schema=schema, result_schema={'type': 'object'}, required_permissions=[action_id]),
            adapter=lambda payload, op=operation: execute(payload, op), allowed_agents=frozenset({'VellumUI'})))
    return PluginContribution(owner=provider, actions=tuple(actions))
