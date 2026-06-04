"""Tool wrapper for deterministic computer-use routing advice."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.computer_use.routing_policy import classify_computer_use_request


@tool
def computer_use_route(instruction: str) -> str:
    """Recommend browser, workspace, desktop, or coming-soon routing for a computer-use request."""

    return json.dumps(classify_computer_use_request(instruction), sort_keys=True)
