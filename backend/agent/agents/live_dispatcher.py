from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import re

from agent.agents.base import SpecialistAgent, SpecialistResponse
from agent.agents.sports import SportsAgent
from agent.master.registry import PupilRegistry
from agent.master.state import MasterThreadStateStore


logger = logging.getLogger(__name__)


@dataclass
class LiveAgentResult:
    handled: bool
    agent_name: str
    answer: str
    status: str = "answered"
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
        registry: PupilRegistry | None = None,
        state_store: MasterThreadStateStore | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        if registry is not None:
            self.registry = registry
        elif sports_agent is not None:
            default_registry = PupilRegistry.default(vault_root=self.vault_root)
            self.registry = PupilRegistry(
                {
                    "XAgent": default_registry.get("XAgent"),
                    "YoutubeAgent": default_registry.get("YoutubeAgent"),
                    "MemoryAgent": default_registry.get("MemoryAgent"),
                    sports_agent.name: sports_agent,
                }
            )
        else:
            self.registry = PupilRegistry.default(vault_root=self.vault_root)
        self.state_store = state_store or MasterThreadStateStore()

    def maybe_handle(self, message: str, thread_id: str) -> LiveAgentResult | None:
        state = self.state_store.get(thread_id)
        active_agent = state.active_agent
        matched_pupil = self.registry.match(message)

        if matched_pupil is not None:
            if active_agent != matched_pupil.name:
                self.state_store.set_active_agent(thread_id, matched_pupil.name)
                self.state_store.clear_pending_reroute(thread_id)
                self._record_handoff(
                    message=message,
                    thread_id=thread_id,
                    agent_name=matched_pupil.name,
                    reason=f"{matched_pupil.name} intent detected",
                )
            try:
                return self._result_from_response(matched_pupil.answer(message))
            except Exception:
                logger.exception("Pupil %s failed while answering.", matched_pupil.name)
                self.state_store.set_active_agent(thread_id, "VellumAgent")
                self.state_store.clear_pending_reroute(thread_id)
                return LiveAgentResult(
                    handled=True,
                    agent_name=matched_pupil.name,
                    status="error",
                    answer=(
                        f"{matched_pupil.name} could not complete this request. "
                        "I routed control back to Vellum so the main agent can continue."
                    ),
                    tools=[self._tool_name(matched_pupil.name)],
                )

        if active_agent != "VellumAgent":
            self.state_store.set_active_agent(thread_id, "VellumAgent")
            self.state_store.clear_pending_reroute(thread_id)
            return None

        return None

    def _result_from_response(self, response: SpecialistResponse) -> LiveAgentResult:
        tools = [self._tool_name(response.agent)]
        if any(source.kind == "web" for source in response.sources):
            tools.append("web_search")
        if "serpapi" in response.analysis.casefold():
            tools.append("serpapi")
        return LiveAgentResult(
            handled=True,
            agent_name=response.agent,
            answer=response.summary,
            status=response.status,
            tools=tools,
            sources=[
                self._source_record(source)
                for source in response.sources
                if source.path_or_url
            ],
        )

    def _record_handoff(self, *, message: str, thread_id: str, agent_name: str, reason: str) -> None:
        folder = self.vault_root / "Agent" / "Queries"
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        slug = re.sub(r"[^A-Za-z0-9]+", "-", message).strip("-").lower()[:60] or "pupil-query"
        path = folder / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slug}.md"
        content = (
            "---\n"
            f"created: \"{now}\"\n"
            f"thread_id: \"{thread_id}\"\n"
            f"routed_to: {agent_name}\n"
            f"reason: \"{reason}\"\n"
            "---\n\n"
            "## Query\n"
            f"{message}\n"
        )
        path.write_text(content, encoding="utf-8", newline="\n")

    def _domain(self, url: str) -> str:
        match = re.match(r"https?://(?:www\.)?([^/]+)", url)
        return match.group(1) if match else ""

    def _source_record(self, source) -> dict[str, str]:
        domain = self._domain(source.path_or_url) if source.kind == "web" else source.kind
        return {
            "url": source.path_or_url,
            "title": source.title,
            "snippet": str(getattr(source, "snippet", "") or ""),
            "domain": domain,
            "fetched_at": source.captured_at,
        }

    def _tool_name(self, agent_name: str) -> str:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", agent_name).lower()
        return name[:-6] + "_agent" if name.endswith("_agent") else name
