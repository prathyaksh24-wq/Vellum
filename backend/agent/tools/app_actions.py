"""Model access to the existing App Action catalog and dispatcher."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
from threading import RLock
from typing import Literal

from langchain_core.tools import tool

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import get_app_action_runtime


@dataclass
class ActionSession:
    runtime: object
    context: AppActionContext
    emitted: list[dict] = field(default_factory=list)
    write_results: dict[str, dict] = field(default_factory=dict)
    lock: object = field(default_factory=RLock)


_SESSION: ContextVar[ActionSession | None] = ContextVar('vellum_app_action_session', default=None)


@contextmanager
def app_action_session(context: AppActionContext | None, thread_id: str, runtime=None):
    context = context or AppActionContext(source='nlp')
    session = ActionSession(runtime or get_app_action_runtime(), context.model_copy(update={'source':'nlp','invocation_conversation_id':thread_id}))
    token = _SESSION.set(session)
    try:
        yield session
    finally:
        _SESSION.reset(token)


def drain_app_action_events() -> list[dict]:
    session = _SESSION.get()
    if session is None:
        return []
    events = list(session.emitted)
    session.emitted.clear()
    return events


def app_action_result_guard() -> str | None:
    """Replace model completion claims while any requested write is unapplied."""
    session = _SESSION.get()
    if session is None or not session.write_results:
        return None
    results = list(session.write_results.values())
    pending = [item for item in results if item.get('status') != 'applied' or item.get('result', {}).get('requires_user_selection')]
    if not pending:
        return None
    applied = [item['message'] for item in results if item not in pending and item.get('message')]
    failures = [item.get('message') or 'The requested change was not applied.' for item in pending]
    return '\n\n'.join([*applied, *failures])


def _contains_secret_argument(arguments: dict) -> bool:
    for key, value in arguments.items():
        if key.casefold() in {'secret','api_key','password','access_token','refresh_token'}:
            return True
        if isinstance(value, dict) and _contains_secret_argument(value):
            return True
    return False


@tool
def app_action(operation: Literal['list','inspect','execute'] = 'list', action_id: str = '', arguments: dict | None = None, query: str = '') -> str:
    """Inspect and change Vellum settings, appearance, personalization, models, pets and other registered controls.

    List actions by a short query, inspect an action's argument schema, then execute
    it with that schema. Use this for requests to change Vellum itself, including
    spelling mistakes or shorthand. All changes use the canonical App Action
    permissions, confirmations and receipts. Never request API keys in chat:
    provider.credential.configure without a secret opens the secure field.
    Always inspect the action's schema before executing; arguments must be its
    actual data, not JSON-schema descriptions. For example, settings.device.update
    uses arguments={"patch":{"personalization":{"emoji":"less"}}} to stop
    emojis. A failed receipt means nothing changed; correct the arguments and
    retry, or explain the failure. Never claim it succeeded after an error.
    query is discovery text. For inspect/execute, put the catalog ID in action_id.
    """
    session = _SESSION.get()
    if session is None:
        return json.dumps({'status':'unavailable','message':'App Actions need the current conversation and device context.'})
    catalog = session.runtime.catalog(session.context)
    actions = {action.id:action for action in catalog.actions}
    # Models sometimes put a returned catalog ID in the discovery field.
    # Resolve only exact registered IDs; this never guesses a write target.
    if not action_id and query.strip() in actions:
        action_id = query.strip()
    if operation == 'inspect' and not action_id and query:
        operation = 'list'
    if operation == 'list':
        aliases = {'personality':'personalization','emojis':'emoji','bg':'background','characteristics':'personalization'}
        terms = [aliases.get(term,term) for term in query.casefold().split()]
        matches = [action for action in actions.values() if not terms or any(term in f'{action.id} {action.title} {action.description} {json.dumps(action.argument_schema)}'.casefold() for term in terms)]
        return json.dumps({'actions':[{'id':action.id,'title':action.title,'description':action.description,'confirmation':action.confirmation_rule} for action in matches[:30]],'total_matches':len(matches)})
    definition = actions.get(action_id)
    if definition is None:
        if operation == 'execute' and not session.write_results:
            session.write_results['unresolved_action'] = {'status':'unavailable','message':'That action is unavailable; the requested setting was not changed.'}
        return json.dumps({'status':'unavailable','message':'That action is not available. List the current catalog first.'})
    if operation == 'inspect':
        return definition.model_dump_json()
    arguments = arguments or {}
    if _contains_secret_argument(arguments):
        session.write_results[action_id] = {'status':'blocked','message':'Use the secure credential field; the provider key was not changed.'}
        return json.dumps({'status':'blocked','message':'Use the secure credential field. Secrets must not be passed through the model.'})
    request = AppActionRequest(action_id=action_id, arguments=arguments)
    with session.lock:
        receipt = session.runtime.dispatch(request, session.context)
        session.write_results.pop('unresolved_action', None)
        session.emitted.append({'request':request.model_dump(mode='json'),'receipt':receipt.model_dump(mode='json')})
        if definition.access_class != 'read':
            session.write_results[action_id] = receipt.model_dump(mode='json')
        if receipt.status == 'applied':
            session.context = session.runtime._context_after_receipt(session.context, receipt)
    result = receipt.model_dump(mode='json')
    if receipt.status == 'failed':
        result['argument_schema'] = definition.argument_schema
        result['next_step'] = 'Retry with actual values matching argument_schema; do not pass schema metadata as values.'
    return json.dumps(result)
