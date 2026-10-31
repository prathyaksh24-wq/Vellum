"""Reuse observed reads inside one user turn, through the existing ToolNode.

No cross-turn cache, mutation replay or additional tool execution owner.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode


def _has_action(value: Any, depth: int = 0) -> bool:
    if depth > 8:
        return True
    if isinstance(value, dict):
        if any(child and (key in {'action', 'action_request', 'pending_action', 'playback_request'} or
                          'receipt' in key or 'confirmation' in key) for key, child in value.items()):
            return True
        return any(_has_action(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        return any(_has_action(item, depth + 1) for item in value)
    return False


def reusable_result(message: ToolMessage, *, delegation: bool = False) -> bool:
    from agent.tools.registry import tool_result_failed
    if tool_result_failed(message):
        return False
    try:
        value = json.loads(message.content)
    except (ValueError, TypeError):
        return not delegation
    if isinstance(value, dict) and (value.get('error') or value.get('ok') is False or
            value.get('status') in ('error', 'failed', 'blocked', 'unavailable')):
        return False
    return not _has_action(value) and (not delegation or isinstance(value, dict) and value.get('status') == 'answered')


def repeated_read_batch(state: dict) -> bool:
    results = []
    for message in reversed(state.get('messages', [])):
        if message.type != 'tool':
            break
        results.append(message)
    return bool(results) and all(m.additional_kwargs.get('vellum_reused_read') for m in results)


def reuse_tool_node(tools):
    node = ToolNode(tools)
    by_name = {tool.name: tool for tool in tools}

    def key(call):
        from agent.tools.tool_search import unwrap_bridge_call
        name, arguments = unwrap_bridge_call(call['name'], call.get('args') or {})
        return name, json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)

    def is_read(call):
        tool = by_name.get(key(call)[0])
        metadata = (getattr(tool, 'metadata', None) or {})
        if 'vellum_access' in metadata:
            return metadata['vellum_access'] == 'read'
        return metadata.get('read_only') is True

    def plan(state):
        messages = state['messages']
        cache, calls, unsafe = {}, {}, set()
        for message in messages[:-1]:
            if message.type == 'human':
                cache, calls, unsafe = {}, {}, set()
            elif message.type == 'ai':
                batch = list(message.tool_calls)
                if any(not is_read(call) for call in batch):
                    cache.clear()
                    unsafe.update(call['id'] for call in batch)
                calls.update((call['id'], call) for call in batch)
            elif message.type == 'tool':
                call = calls.get(message.tool_call_id)
                if call and message.tool_call_id not in unsafe:
                    delegation = key(call)[0] == 'delegate_to_agent'
                    if reusable_result(message, delegation=delegation):
                        cache[key(call)] = message
                    else:
                        cache.clear()
        requested = list(messages[-1].tool_calls)
        batch_read = all(is_read(call) for call in requested)
        pending, reused, aliases, first = [], {}, {}, {}
        for call in requested:
            identity = key(call)
            if batch_read and identity in cache:
                reused[call['id']] = cache[identity]
            elif batch_read and identity in first and identity[0] != 'delegate_to_agent':
                aliases[call['id']] = first[identity]
            else:
                pending.append(call)
                first[identity] = call['id']
        subset = {**state, 'messages': [*messages[:-1], messages[-1].model_copy(update={'tool_calls': pending})]}
        return requested, subset, reused, aliases

    def finish(requested, result, reused, aliases):
        outputs = {message.tool_call_id: message for message in result.get('messages', [])}
        for target, source in aliases.items():
            # Unknown/failed/delegated writes are not memoized across rounds.
            reused[target] = outputs[source]
        for call in requested:
            if call['id'] in reused:
                old = reused[call['id']]
                outputs[call['id']] = old.model_copy(update={'id': None, 'name': call['name'],
                    'tool_call_id': call['id'], 'additional_kwargs': {**old.additional_kwargs, 'vellum_reused_read': True}})
        return {'messages': [outputs[call['id']] for call in requested]}

    def invoke(state, config):
        requested, subset, reused, aliases = plan(state)
        result = node.invoke(subset, config) if subset['messages'][-1].tool_calls else {'messages': []}
        return finish(requested, result, reused, aliases)

    async def ainvoke(state, config):
        requested, subset, reused, aliases = plan(state)
        result = await node.ainvoke(subset, config) if subset['messages'][-1].tool_calls else {'messages': []}
        return finish(requested, result, reused, aliases)

    return RunnableLambda(invoke, afunc=ainvoke)
