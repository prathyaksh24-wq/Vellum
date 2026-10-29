"""Model access to the existing App Action catalog and dispatcher."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import re
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
    google_reads: set[str] = field(default_factory=set)
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


def note_google_read(service: str) -> None:
    session = _SESSION.get()
    if session is not None:
        with session.lock:
            session.google_reads.add(service)


def app_action_read_only_google_turn() -> bool:
    """Buffer provider text until its claims can be checked against write receipts."""
    session = _SESSION.get()
    return session is not None and bool(session.google_reads) and not session.write_results


def app_action_result_guard(answer: str = '') -> str | None:
    """Replace model completion claims while any requested write is unapplied."""
    session = _SESSION.get()
    if session is None:
        return None
    if not session.write_results:
        # A first-person completion claim is not evidence that a read performed a
        # write. Do not reject descriptions of events that already exist.
        claim = re.search(r"(?:^|[.!?]\s+|\n)\s*(?:i|we)(?:['’](?:ve|d)| have| had)?\s+(?:successfully\s+)?(?:scheduled|booked|created|added|saved|sent|deleted|removed|updated|renamed|changed|rescheduled|cancelled|canceled|trashed)\b", answer, re.I)
        if claim and session.google_reads:
            if session.google_reads == {'calendar'}:
                return "I checked Google Calendar, but I haven't created or changed an event. There is no confirmed booking from this request."
            return "I read the connected Google data, but there is no successful write receipt for this request. I haven't confirmed the requested change."
        return None
    results = list(session.write_results.values())
    pending = [item for item in results if item.get('status') != 'applied' or item.get('result', {}).get('requires_user_selection')]
    if not pending:
        return None
    applied = [item['message'] for item in results if item not in pending and item.get('message')]
    failures = [item.get('message') or 'The requested change was not applied.' for item in pending]
    return '\n\n'.join([*applied, *failures])


def app_action_confirmation_pending() -> bool:
    """A prepared review is authoritative; no model pass is needed to rewrite it."""
    session = _SESSION.get()
    return session is not None and any(
        result.get('status') == 'confirmation_required'
        for result in session.write_results.values()
    )


def _contains_secret_argument(arguments: dict) -> bool:
    for key, value in arguments.items():
        if key.casefold() in {'secret','api_key','password','access_token','refresh_token'}:
            return True
        if isinstance(value, dict) and _contains_secret_argument(value):
            return True
    return False


def _google_tool_hint(action_id: str) -> dict:
    """Recover a known published method name without guessing or executing a write."""
    from agent.plugins import google_api_catalog as catalog
    method_id = action_id.removeprefix('google.')
    for service in catalog.ROOTS:
        if method_id in catalog.methods(service):
            details = catalog.describe(service, method_id)
            schema = details['parameters']
            if details['body'] is not None:
                schema['properties']['body'] = details['body']
            return {'suggested_tool': {'name': catalog.tool_name(service, method_id),
                'argument_schema': schema},
                'next_step': 'Use tool_search with the suggested tool name, then call that discovered tool with actual values matching argument_schema. It prepares the required review; do not invent an App Action ID.'}
    return {}


@tool
def app_action(operation: Literal['list','inspect','execute'] = 'list', action_id: str = '', arguments: dict | None = None, query: str = '') -> str:
    """Inspect and change Vellum settings and registered connected-service data.
    Includes appearance, personalization, models, pets and connector App Actions.

    List actions by a short query, inspect an action's argument schema, then execute
    it with that schema. Use this for Vellum controls and confirmed external writes, including
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
    if action_id and action_id not in actions:
        # A tool name is not an action ID. Do not silently ignore an invalid ID
        # on list and return the first 30 unrelated actions on every retry.
        if operation == 'execute' and not session.write_results:
            session.write_results['unresolved_action'] = {'status':'unavailable','message':'That action is unavailable; the requested change was not applied.'}
        terms = [term for term in re.split(r"[\W_]+", action_id.casefold()) if len(term) > 2]
        matches = [action for action in actions.values()
                   if any(term in f'{action.id} {action.title}'.casefold() for term in terms[:1])]
        return json.dumps({'status':'unavailable',
            'message':'This is not a registered App Action ID. Reads use their discovered tool through tool_call. For writes inspect an exact action ID below before execute.',
            'actions':[{'id':action.id,'title':action.title,'confirmation':action.confirmation_rule} for action in matches[:5]],
            'discovery_example':{'operation':'list','query':terms[0] if terms else action_id},
            'available_operations':['list','inspect','execute'],
            **(_google_tool_hint(action_id) if action_id.startswith('google.') else {})})
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
        if action_id == 'google.api.execute':
            result['next_step'] = 'Google arguments must contain service, method_id and parameters (IDs go inside parameters), plus body when required. Prefer tool_search and the exact discovered Google tool; it wraps these fields and prepares the review. Do not repeat the same failed arguments or redo a successful target lookup.'
    return json.dumps(result)
