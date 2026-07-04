from __future__ import annotations

import argparse
import os
from queue import Empty, Queue
import secrets
import sys
from threading import Thread
import time
from typing import Any
from uuid import uuid4

from agent.runtime.protocol import ProtocolMessage, encode_message, parse_message, validate_envelope


def _emit(message_type: str, run_id: str, task_id: str, payload: dict[str, Any]) -> None:
    sys.stdout.write(encode_message(message_type, run_id, task_id, payload) + "\n")
    sys.stdout.flush()


def _input(queue: Queue[ProtocolMessage | BaseException | None]) -> None:
    try:
        for line in sys.stdin:
            if line.strip():
                queue.put(parse_message(line))
    except BaseException as exc:
        queue.put(exc)
    finally:
        queue.put(None)


def run_worker(run_id: str, task_id: str) -> int:
    token = os.environ.get("VELLUM_WORKER_TOKEN", "")
    interval = max(0.01, float(os.environ.get("VELLUM_HEARTBEAT_INTERVAL", "1")))
    incoming: Queue[ProtocolMessage | BaseException | None] = Queue()
    Thread(target=_input, args=(incoming,), daemon=True).start()
    _emit("progress", run_id, task_id, {"event": "hello", "token": token})

    try:
        first = incoming.get(timeout=10)
    except Empty:
        return 2
    if not isinstance(first, ProtocolMessage):
        return 2
    try:
        validate_envelope(first, run_id=run_id, task_id=task_id)
    except ValueError:
        return 2
    supplied = str(first.payload.pop("auth_token", ""))
    if first.type != "run" or not token or not secrets.compare_digest(supplied, token):
        return 2

    payload = first.payload
    if payload.get("inspect_environment"):
        _emit("result", run_id, task_id, {
            "status": "completed", "cwd": os.getcwd(),
            "has_openrouter_key": "OPENROUTER_API_KEY" in os.environ,
        })
        return 0

    request = payload.get("tool_request")
    if isinstance(request, dict):
        request_id = str(uuid4())
        _emit("tool_request", run_id, task_id, {**request, "request_id": request_id})
        if _wait_for(incoming, run_id, task_id, interval, request_id=request_id):
            _emit("result", run_id, task_id, {"status": "cancelled"})
            return 0

    deadline = time.monotonic() + max(0.0, float(payload.get("sleep", 0)))
    while time.monotonic() < deadline:
        _emit("heartbeat", run_id, task_id, {"at": time.time()})
        try:
            message = incoming.get(timeout=min(interval, max(0.0, deadline - time.monotonic())))
        except Empty:
            continue
        if isinstance(message, ProtocolMessage) and message.type == "cancel":
            _emit("result", run_id, task_id, {"status": "cancelled"})
            return 0
    _emit("result", run_id, task_id, {"status": "completed", "value": payload.get("result")})
    return 0


def _wait_for(queue: Queue[ProtocolMessage | BaseException | None], run_id: str, task_id: str, interval: float, *, request_id: str) -> bool:
    while True:
        try:
            message = queue.get(timeout=interval)
        except Empty:
            _emit("heartbeat", run_id, task_id, {"at": time.time()})
            continue
        if not isinstance(message, ProtocolMessage):
            return True
        validate_envelope(message, run_id=run_id, task_id=task_id)
        if message.type == "cancel":
            return True
        if message.type == "tool_result" and message.payload.get("request_id") == request_id:
            return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    return run_worker(args.run_id, args.task_id)


if __name__ == "__main__":
    raise SystemExit(main())
