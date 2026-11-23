"""A user turn as Vellum handles it now that the model, not a keyword router,
chooses the specialist (ADR 0009).

The user's yes or no to a pending specialist action still goes through the
dispatcher. Anything else is what the model's ``delegate_to_agent`` tool does when
it picks ``agent_id``: delegate the message and keep any action the specialist
prepares as the thread's pending action.
"""
from __future__ import annotations

from agent.master.runtime import DelegationRequest


def turn(dispatcher, agent_id, message, thread_id="chat", **_ignored):
    handled = dispatcher.maybe_handle(message, thread_id)
    if handled is not None:
        return handled
    from agent.tools.delegation import record_specialist_outcome

    run = dispatcher.delegation_runtime.delegate(
        DelegationRequest(agent_id=agent_id, task=message, parent_thread_id=thread_id))
    response = record_specialist_outcome(dispatcher.state_store, thread_id, run.response)
    return dispatcher._result_from_response(response, run=run, route_source="model")
