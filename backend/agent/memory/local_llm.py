"""Small local-Ollama calls for memory work.

Memory content is personal, so selection, summarizing and import parsing run
on the local model only. Callers must handle ``LocalLLMError`` and fall back;
memory features never block a chat on the model being available.
"""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator
from typing import Any


class LocalLLMError(RuntimeError):
    pass


def _endpoint() -> tuple[str, str]:
    from agent.config import get_settings

    settings = get_settings()
    return settings.ollama_base_url.rstrip("/"), settings.memory_llm_model


def shared_context(model: str) -> dict[str, int]:
    """Ask Ollama for the same context size chat uses for this model.

    Ollama loads a separate copy of a model for each context size, so memory
    work at its own size doubled GPU memory and pushed models onto the
    processor. Matching chat's window shares the one loaded copy.
    """
    try:
        from agent.config import get_settings
        from agent.llm.context_sizing import local_window

        return {"num_ctx": int(local_window(f"ollama/{model}", get_settings()))}
    except Exception:  # noqa: BLE001 - fall back to Ollama's default
        return {}


def _body(system: str, prompt: str, *, model: str, json_mode: bool, stream: bool, max_tokens: int) -> bytes:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream": stream,
        "think": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens, **shared_context(model)},
    }
    if json_mode:
        payload["format"] = "json"
    return json.dumps(payload).encode("utf-8")


def complete(system: str, prompt: str, *, json_mode: bool = False, timeout: float = 30.0,
             max_tokens: int = 800, model: str | None = None) -> str:
    base, default_model = _endpoint()
    request = urllib.request.Request(
        f"{base}/api/chat",
        data=_body(system, prompt, model=model or default_model, json_mode=json_mode, stream=False,
                   max_tokens=max_tokens),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - local Ollama
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise LocalLLMError(str(exc)) from exc
    return str((data.get("message") or {}).get("content") or "")


def complete_json(system: str, prompt: str, *, timeout: float = 30.0, max_tokens: int = 800) -> Any:
    text = complete(system, prompt, json_mode=True, timeout=timeout, max_tokens=max_tokens)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LocalLLMError(f"model returned invalid JSON: {exc}") from exc


def stream(system: str, prompt: str, *, timeout: float = 120.0, max_tokens: int = 1800,
           model: str | None = None) -> Iterator[str]:
    """Yield text deltas as the local model writes them."""
    base, default_model = _endpoint()
    request = urllib.request.Request(
        f"{base}/api/chat",
        data=_body(system, prompt, model=model or default_model, json_mode=False, stream=True,
                   max_tokens=max_tokens),
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - local Ollama
    except Exception as exc:  # noqa: BLE001
        raise LocalLLMError(str(exc)) from exc
    with response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            delta = str((chunk.get("message") or {}).get("content") or "")
            if delta:
                yield delta
            if chunk.get("done"):
                break
