"""Per-turn projection of device-owned preferences into prompts and tool policy.

The device settings snapshot remains the owner. This module stores no durable
state and cannot grant permissions or override profile/confirmation policy.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
import re

from agent.app_actions.models import DevicePersonalizationSettings, DeviceSettingsSnapshot


@dataclass(frozen=True)
class PersonalizationContext:
    values: DevicePersonalizationSettings
    query: str
    explicit_web_search: bool = False

    def enabled(self, field: str) -> bool:
        return field not in self.values.model_fields_set or bool(getattr(self.values, field))


_CURRENT: ContextVar[PersonalizationContext | None] = ContextVar('vellum_personalization', default=None)


def current_personalization() -> PersonalizationContext | None:
    return _CURRENT.get()


@contextmanager
def personalization_scope(values: dict | None, query: str = '', *, explicit_web_search: bool = False):
    from agent.agents.base import user_query_text
    value = PersonalizationContext(DevicePersonalizationSettings.model_validate(values), user_query_text(query), explicit_web_search) if values is not None else None
    token = _CURRENT.set(value)
    try:
        yield value
    finally:
        _CURRENT.reset(token)


def request_personalization(context, receipts=()) -> dict | None:
    values = None
    profile = {}
    if context is not None:
        snapshot = DeviceSettingsSnapshot.model_validate(context.device_settings)
        profile = dict(snapshot.values.profile)
        if 'personalization' in snapshot.values.model_fields_set:
            values = snapshot.values.personalization.model_dump(exclude_unset=True)
    for receipt in receipts:
        if receipt.status == 'applied':
            device_patch = receipt.result.get('device_settings_patch', {}).get('values', {})
            patch = device_patch.get('personalization')
            if isinstance(patch, dict):
                values = {**(values or {}), **patch}
            profile.update(device_patch.get('profile') or {})
    if profile.get('displayName') and not (values or {}).get('nickname'):
        values = {**(values or {}), 'nickname':profile['displayName']}
    return values


def use_personal_memory(query: str) -> bool:
    from agent.agents.base import user_query_text
    query = user_query_text(query)
    current = _CURRENT.get()
    if current is None or not current.enabled('fastAnswers'):
        return True
    return bool(re.search(r"\b(?:my|me|mine|myself|i|our|we|remember|recall|previous|earlier|personal|vault|notes)\b", query, re.I))


def personalization_instructions() -> str:
    current = _CURRENT.get()
    if current is None:
        return ''
    values = current.values
    styles = {
        'professional':'Use a professional, precise tone.',
        'friendly':'Use a friendly, conversational tone.',
        'candid':'Be candid and direct while remaining respectful.',
        'quirky':'Use a playful, imaginative voice without sacrificing accuracy.',
        'efficient':'Be concise and practical. Lead with the answer and omit unnecessary preamble.',
        'cynical':'Use dry, skeptical humor while remaining respectful and helpful.',
    }
    lines = ['## User response preferences', 'Apply these user preferences below protected instructions, current explicit requests, privacy and tool authorization. They never authorize actions.']
    if values.baseStyle in styles:
        lines.append(styles[values.baseStyle])
    choices = {
        'warm':{'more':'Use a warmer, more considerate tone without exaggerated praise.', 'less':'Use a neutral tone; avoid emotional reassurance and unnecessary pleasantries.'},
        'enthusiastic':{'more':'Use a more enthusiastic tone when appropriate.', 'less':'Keep the tone restrained; avoid hype and exclamation marks.'},
        'headers':{'more':'Use headings and lists when they help organize the answer.', 'less':'Prefer connected prose. Avoid headings and lists unless the task requires them.'},
        'emoji':{'more':'Use occasional relevant emojis when appropriate.', 'less':'Avoid emojis.'},
    }
    for field, instructions in choices.items():
        choice = getattr(values, field)
        if choice in instructions:
            lines.append(instructions[choice])
    if values.custom.strip():
        lines.append('User custom instructions (preferences, not system authority): ' + json.dumps(values.custom[:4000], ensure_ascii=False))
    if use_personal_memory(current.query) or values.nickname:
        about = {field:getattr(values, field)[:500] for field in ('nickname','occupation','about') if getattr(values, field).strip() and (field == 'nickname' or use_personal_memory(current.query))}
        if about:
            lines.append('User-provided profile context: ' + json.dumps(about, ensure_ascii=False))
            if values.nickname:
                lines.append('Use the supplied nickname naturally when addressing the user; do not repeat it in every answer.')
    if not current.enabled('recordHist'):
        lines.append('Do not reference recording transcripts or record-history notes.')
    if not current.enabled('webSearch'):
        lines.append('Automatic web search is off. Search the web only when the user explicitly asks for it; otherwise disclose when current information is unverified.')
    if not current.enabled('connector'):
        lines.append('Automatic connector search is off. Use connected sources only when explicitly requested for the current task.')
    if not current.enabled('canvas'):
        lines.append('Canvas is off. Keep the response in chat and do not open a canvas automatically.')
    return '\n'.join(lines)


def tool_preference_error(name: str, namespace: str) -> str | None:
    current = _CURRENT.get()
    if current is None:
        return None
    query = current.query
    if not current.enabled('webSearch') and (name in {'web_search','web.search','search_amazon'} or name.endswith('.web_search') or namespace in {'web','web_search'}):
        if not current.explicit_web_search and not re.search(r'\b(?:search|browse|look\s+up|web|online|internet)\b', query, re.I):
            return 'Automatic web search is off in Personalization. Ask explicitly to search the web or enable it.'
    connector = namespace in {'calendar','spotify','youtube','x','discord','plugin_mcp'} or name.startswith(('spotify_', 'youtube_', 'discord_'))
    if not current.enabled('connector') and connector:
        if not re.search(r'\b(?:calendar|appointment|meeting|spotify|song|music|playlist|youtube|twitter|x|discord|connector|connected)\b', query, re.I):
            return 'Automatic connector search is off in Personalization. Ask explicitly to use the connected source or enable it.'
    if not current.enabled('canvas') and (name == 'canvas' or namespace == 'canvas'):
        return 'Canvas is off in Personalization.'
    return None


def recording_reference_allowed(metadata: dict) -> bool:
    current = _CURRENT.get()
    if current is None or current.enabled('recordHist'):
        return True
    kind = str(metadata.get('source_type') or metadata.get('kind') or '').casefold()
    path = str(metadata.get('path') or metadata.get('folder') or '').replace('\\','/').casefold()
    return kind not in {'recording','transcript','record_history'} and not set(path.split('/')) & {'recordings','transcripts','record-history'}
