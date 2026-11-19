"""The model's view of its own long-conversation context.

Four small tools, modelled on billion-context's compress / decompress /
search_context / status, backed by Vellum's own owners: the context archive
(summaries and compacted transcripts), the evidence store (tool results) and
the saved chat. Compaction stays automatic; these let the model look back,
check pressure, and free room on purpose. Every result is scoped to the
current conversation and returned as untrusted history, never instructions.
"""
from __future__ import annotations

import json

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


def _thread(config) -> str:
    return str(((config or {}).get('configurable') or {}).get('thread_id') or '')


def _unavailable() -> str:
    return json.dumps({'ok': False, 'error': 'Current conversation identity is unavailable.'})


@tool
def context_status(config: RunnableConfig = None) -> str:
    """How full this chat's context window is, what fills it, and what was compacted.

    Returns window, used and free tokens by layer, compactions, summary blocks
    (searchable and decompressible) and stored tool results.
    """
    from agent.conversations.context_archive import context_archive
    from agent.conversations.evidence import evidence_store
    thread_id = _thread(config)
    if not thread_id:
        return _unavailable()
    archive = context_archive()
    report = archive.state(thread_id)['report']
    blocks = archive.blocks(thread_id)
    used = int(report.get('estimated_input_tokens') or 0)
    window = int(report.get('context_window') or 0)
    return json.dumps({
        'ok': True, 'context_window': window, 'used_tokens': used,
        'used_share': round(used / window, 3) if window else None,
        'free_tokens': max(0, int(report.get('input_limit') or 0) - used) if window else None,
        'reply_reserve': report.get('output_reserved'), 'layers': report.get('layers', {}),
        'compactions': report.get('compaction_count', 0),
        'summaries': [{'block_id': block['block_id'], 'level': block['level'], 'ready': bool(block['summary'])}
                      for block in blocks],
        'stored_tool_results': evidence_store().count(thread_id),
    }, ensure_ascii=False)


@tool
def search_context(query: str, config: RunnableConfig = None) -> str:
    """Search everything earlier in THIS chat: summaries, compacted messages, saved
    messages and stored tool results. Returns passages with block_id, message
    or evidence_id pointers; open them with decompress or conversation_history.
    """
    from agent.conversations.context_archive import context_archive
    from agent.conversations.evidence import evidence_store
    from agent.conversations.recall import read_history, recall_history
    thread_id = _thread(config)
    if not thread_id:
        return _unavailable()
    if not query.strip():
        return json.dumps({'ok': False, 'error': 'Give search terms.'})
    query = query[:500]
    result = {'ok': True, 'untrusted_history': True,
              'summaries_and_compacted': context_archive().search(thread_id, query, limit=6),
              'tool_results': evidence_store().search(thread_id, query, limit=4)}
    try:
        saved = recall_history(read_history(), thread_id=thread_id, query=query, scope='current', limit=4)
        result['saved_messages'] = saved.get('messages', []) if isinstance(saved, dict) else []
    except Exception:  # noqa: BLE001 - the archive and evidence results still stand
        result['saved_messages'] = []
    return json.dumps(result, ensure_ascii=False, default=str)


@tool
def decompress(block_id: str, page: int = 1, config: RunnableConfig = None) -> str:
    """Open a summary's original messages (block_id from the context summary,
    search_context or context_status). Long ranges are paged: page=2, 3...
    A merged summary lists its parts; decompress a part for its messages.
    """
    from agent.conversations.context_archive import context_archive
    thread_id = _thread(config)
    if not thread_id:
        return _unavailable()
    return json.dumps(context_archive().decompress(thread_id, block_id.strip(), page=page), ensure_ascii=False)


@tool
def compress(focus: str = '', config: RunnableConfig = None) -> str:
    """Compact older turns of this chat now, before a large step, keeping what
    matters for `focus`. The latest turns stay exact; everything compacted
    stays searchable and decompressible. Compaction also happens automatically.
    """
    from agent.conversations.context_archive import context_archive
    thread_id = _thread(config)
    if not thread_id:
        return _unavailable()
    context_archive().request_compaction(thread_id, focus)
    return json.dumps({'ok': True, 'status': 'scheduled',
                       'note': 'Older turns are compacted before your next step; continue the task.'})
