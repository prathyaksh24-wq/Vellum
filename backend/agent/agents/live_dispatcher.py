from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re

from agent.agents.sports import SportsAgent
from agent.master.state import MasterThreadStateStore


@dataclass
class LiveAgentResult:
    handled: bool
    agent_name: str
    answer: str
    tools: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)


class LiveAgentDispatcher:
    """Parent-owned live delegation layer.

    This is the first concrete Master/Pupil runtime slice: Vellum owns routing
    and final response shape; SportsAgent is a specialist that returns a
    structured response.
    """

    def __init__(
        self,
        vault_root: Path,
        sports_agent: SportsAgent | None = None,
        state_store: MasterThreadStateStore | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.sports_agent = sports_agent or SportsAgent(vault_root=self.vault_root)
        self.state_store = state_store or MasterThreadStateStore()

    def maybe_handle(self, message: str, thread_id: str) -> LiveAgentResult | None:
        state = self.state_store.get(thread_id)
        active_agent = state.active_agent
        sports_intent = self.sports_agent.can_handle(message)

        if active_agent == "SportsAgent" and not sports_intent:
            self.state_store.set_pending_reroute(thread_id, "VellumAgent", "non-sports turn while SportsAgent active")
            return LiveAgentResult(
                handled=True,
                agent_name="SportsAgent",
                answer=(
                    "This looks outside sports. Should I route this back to Vellum "
                    "so the main agent can handle it?"
                ),
                tools=["sports_agent"],
            )

        if not sports_intent:
            return None

        if active_agent != "SportsAgent":
            self.state_store.set_active_agent(thread_id, "SportsAgent")
            self._record_handoff(message=message, thread_id=thread_id, league=self.sports_agent.resolve_league(message))

        response = self.sports_agent.answer(message)
        return LiveAgentResult(
            handled=True,
            agent_name=response.agent,
            answer=response.summary,
            tools=["sports_agent", "web_search"],
            sources=[
                {
                    "url": source.path_or_url,
                    "title": source.title,
                    "snippet": "",
                    "domain": self._domain(source.path_or_url),
                    "fetched_at": source.captured_at,
                }
                for source in response.sources
                if source.kind == "web" and source.path_or_url
            ],
        )

    def _record_handoff(self, *, message: str, thread_id: str, league: str) -> None:
        folder = self.vault_root / "Agent" / "Queries"
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        slug = re.sub(r"[^A-Za-z0-9]+", "-", message).strip("-").lower()[:60] or "sports-query"
        path = folder / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slug}.md"
        content = (
            "---\n"
            f"created: \"{now}\"\n"
            f"thread_id: \"{thread_id}\"\n"
            "routed_to: SportsAgent\n"
            f"resolved_league: \"{league}\"\n"
            "reason: \"sports intent detected\"\n"
            "---\n\n"
            "## Query\n"
            f"{message}\n"
        )
        path.write_text(content, encoding="utf-8", newline="\n")

    def _domain(self, url: str) -> str:
        match = re.match(r"https?://(?:www\.)?([^/]+)", url)
        return match.group(1) if match else ""
