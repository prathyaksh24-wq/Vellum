# Vellum Agent Swarm Sports Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working Vellum specialist-agent vertical slice: SportsAgent routing, daemon-driven sports curiosity, disabled UFC/boxing, and memory-proposal scaffolding.

**Architecture:** Vellum remains the main agent and final responder. Specialist agents expose a typed response contract; SportsAgent wraps existing sports curiosity/fetch behavior; `vellum-daemon` runs a local sports loop that evaluates curiosity and refreshes sports snapshots without turning Vellum into a thin switchboard.

**Tech Stack:** Python 3.11+, Pydantic, LangChain tool wrappers, pytest, PowerShell start scripts, existing SerpAPI importer and Obsidian vault layout.

---

## Codex Subagent Reference

This plan follows OpenAI Codex's documented subagent shape as a design reference:

- specialists are narrow and opinionated
- the parent orchestrates delegation and consolidates results
- subagents inherit safety controls unless narrowed
- concurrency and nesting need explicit caps
- structured results are preferred when many agents or repeated jobs are involved

Vellum runtime subagents are Python services, not Codex `.toml` custom agents. Project-scoped `.codex/agents/*.toml` files can be added later for development-time workflows, but this implementation keeps runtime behavior in `backend/agent/agents/`.

## Scope Check

The design spec covers sports, X, Youtube, MemoryAgent, MCPAgent, and long-term swarm behavior. This plan intentionally implements the first testable slice:

- shared specialist response contract
- SportsAgent
- main-agent sports routing hooks
- sports daemon loop
- disabled UFC/boxing
- memory proposal and retention-aware paths
- X/Youtube/Memory specialist stubs that return explicit `blocked` or `needs_fetch` responses

Full X/Youtube daemon loops and MCPAgent are deferred to separate plans after the SportsAgent path is verified end to end.

## File Structure

- Create `backend/agent/agents/__init__.py`: exports specialist classes and schema.
- Create `backend/agent/agents/base.py`: Pydantic response/source/memory proposal models and a `SpecialistAgent` protocol.
- Create `backend/agent/agents/sports.py`: SportsAgent intent detection, fetch delegation, and vault snapshot lookup.
- Create `backend/agent/agents/x_agent.py`: XAgent stub with contract-compatible responses.
- Create `backend/agent/agents/youtube.py`: YoutubeAgent stub with contract-compatible responses.
- Create `backend/agent/agents/memory_agent.py`: MemoryAgent stub that accepts proposals but does not mutate shared memory.
- Create `backend/agent/agents/router.py`: deterministic routing helper used by tests and future main-agent integration.
- Create `backend/agent/agents/skill_router.py`: maps active Vellum skills with `route_to_agent` metadata to specialist routes.
- Create `backend/agent/agents/orchestrator.py`: depth/concurrency-aware specialist delegation helper.
- Create `.skills/active/skill-route-sports-agent-v1.json`: runtime skill that routes enabled sports questions to SportsAgent.
- Create `backend/agent/daemon/__init__.py`: daemon package marker.
- Create `backend/agent/daemon/main.py`: CLI entrypoint for `vellum-daemon`.
- Create `backend/agent/daemon/loops/__init__.py`: daemon loops package marker.
- Create `backend/agent/daemon/loops/sports.py`: one daemon tick for sports curiosity.
- Modify `backend/agent/config.py`: daemon interval and enabled sports settings.
- Modify `backend/agent/graph/agent.py`: update prompt and tool wording to remove UFC/boxing and explain specialist routing.
- Modify `backend/agent/tools/sports_curiosity.py`: use enabled leagues and expose pure helpers cleanly.
- Modify `scripts/import_sports_snapshots.py`: stop default fetching for UFC/boxing and keep disabled leagues unavailable unless explicitly re-enabled in code later.
- Modify `scripts/seed_sports_folder.py`: seed only enabled leagues plus optional Ambient.
- Create `scripts/start-daemon.ps1`: start the local daemon with a pid/log file.
- Create `scripts/stop-daemon.ps1`: stop the local daemon.
- Modify `backend/pyproject.toml`: add `vellum-daemon = "agent.daemon.main:main"` script.
- Replace or rewrite `backend/tests/test_sports_importer.py`: align tests with `Vault/Library/Sports/...` current layout.
- Create `backend/tests/test_specialist_agents.py`: schema, router, SportsAgent tests.
- Create `backend/tests/test_skill_driven_routing.py`: active skill routing tests.
- Create `backend/tests/test_specialist_orchestrator.py`: delegation caps and parent-consolidation behavior.
- Create `backend/tests/test_sports_daemon.py`: daemon tick tests.

## Task 1: Normalize Enabled Sports and Fix Importer Tests

**Files:**
- Modify: `scripts/import_sports_snapshots.py`
- Modify: `scripts/seed_sports_folder.py`
- Modify: `backend/agent/tools/sports_curiosity.py`
- Modify: `backend/agent/graph/agent.py`
- Replace: `backend/tests/test_sports_importer.py`

- [ ] **Step 1: Replace importer tests with current-layout failing tests**

Replace `backend/tests/test_sports_importer.py` with:

```python
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_sports_snapshots.py"


def load_importer():
    assert SCRIPT_PATH.exists(), "scripts/import_sports_snapshots.py should exist"
    spec = importlib.util.spec_from_file_location("import_sports_snapshots", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self):
        self.calls = []

    def serpapi_search(self, query, token):
        self.calls.append((query, token))
        return {
            "search_metadata": {"status": "Success"},
            "sports_results": {
                "title": query,
                "game_spotlight": {
                    "teams": [
                        {"name": "Arsenal", "score": "2"},
                        {"name": "PSG", "score": "1"},
                    ],
                    "status": "Final",
                },
            },
            "top_stories": [{"title": "Arsenal analysis", "source": "Example", "date": "Today"}],
        }


def test_default_run_writes_enabled_library_sports_snapshots(tmp_path):
    sports_importer = load_importer()
    result = sports_importer.run(
        project_root=tmp_path,
        leagues=None,
        dry_run=False,
        curiosity_reason="test run",
        client=FakeClient(),
        serpapi_token="serp-token",
    )

    sports = tmp_path / "Vault" / "Library" / "Sports"
    records = [json.loads(line) for line in (sports / "sports-snapshots.jsonl").read_text(encoding="utf-8").splitlines()]
    leagues = {record["league"] for record in records}

    assert result == 0
    assert leagues == {"NBA", "Formula-One", "Premier-League", "Champions-League", "Ambient"}
    assert "UFC" not in leagues
    assert "Boxing" not in leagues
    assert (sports / "NBA" / "latest.md").exists()
    assert any((sports / "Champions-League" / "snapshots" / "2026").glob("*.md"))


def test_dry_run_reports_paths_without_writing_or_network(tmp_path):
    sports_importer = load_importer()
    client = FakeClient()

    result = sports_importer.run(
        project_root=tmp_path,
        leagues=["NBA"],
        dry_run=True,
        curiosity_reason="dry run",
        client=client,
        serpapi_token="serp-token",
    )

    assert result == 0
    assert client.calls == []
    assert not (tmp_path / "Vault" / "Library" / "Sports").exists()


def test_disabled_league_is_rejected_even_when_requested(tmp_path):
    sports_importer = load_importer()
    result = sports_importer.run(
        project_root=tmp_path,
        leagues=["UFC"],
        dry_run=False,
        curiosity_reason="disabled league",
        client=FakeClient(),
        serpapi_token="serp-token",
    )

    sports = tmp_path / "Vault" / "Library" / "Sports"
    assert result == 0
    assert not (sports / "UFC").exists()
    records_path = sports / "sports-snapshots.jsonl"
    assert not records_path.exists()
```

- [ ] **Step 2: Run importer tests and verify they fail**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_sports_importer.py -v
```

Expected: failures showing the old importer still includes disabled leagues or writes different paths.

- [ ] **Step 3: Add enabled/disabled league constants to importer**

In `scripts/import_sports_snapshots.py`, replace the current `LEAGUES` block with:

```python
ENABLED_LEAGUES: tuple[str, ...] = (
    "NBA",
    "Formula-One",
    "Premier-League",
    "Champions-League",
    "Ambient",
)

DISABLED_LEAGUES: tuple[str, ...] = (
    "Boxing",
    "UFC",
)

LEAGUES: tuple[str, ...] = ENABLED_LEAGUES
ALL_KNOWN_LEAGUES: tuple[str, ...] = ENABLED_LEAGUES + DISABLED_LEAGUES
```

Then update the CLI argument choices from `choices=LEAGUES` to `choices=ALL_KNOWN_LEAGUES`.

- [ ] **Step 4: Reject disabled leagues in importer `run`**

In `scripts/import_sports_snapshots.py`, inside `run`, set targets and rejection behavior to:

```python
targets = leagues or list(ENABLED_LEAGUES)

results: list[dict[str, Any]] = []
for league in targets:
    if league in DISABLED_LEAGUES:
        results.append({"league": league, "skipped": True, "reason": "disabled"})
        continue
    if league not in FETCHERS:
        results.append({"league": league, "skipped": True, "reason": "unknown league"})
        continue
    results.append(
        FETCHERS[league](
            vault=vault,
            project_root=project_root,
            client=client,
            serpapi_token=serpapi_token,
            curiosity_reason=curiosity_reason,
            dry_run=dry_run,
        )
    )
```

- [ ] **Step 5: Update seed script defaults**

In `scripts/seed_sports_folder.py`, import `ENABLED_LEAGUES` and `DISABLED_LEAGUES`:

```python
from import_sports_snapshots import (
    DISABLED_LEAGUES,
    ENABLED_LEAGUES,
    QUERY_TEMPLATES,
    utc_now_iso,
    vault_path,
    write_text,
    yaml_quote,
)
```

Replace loops over `LEAGUES` with `ENABLED_LEAGUES`. Leave `SEASON_DEFAULTS` and `LEAGUE_KEYWORDS` entries for disabled leagues only if tests require historical compatibility; do not seed their folders.

- [ ] **Step 6: Update sports curiosity enabled leagues**

In `backend/agent/tools/sports_curiosity.py`, replace the `LEAGUES` tuple with:

```python
ENABLED_LEAGUES = (
    "NBA",
    "Formula-One",
    "Premier-League",
    "Champions-League",
    "Ambient",
)

DISABLED_LEAGUES = (
    "Boxing",
    "UFC",
)

LEAGUES = ENABLED_LEAGUES
```

In `_gate`, add disabled handling before unknown handling:

```python
if league in DISABLED_LEAGUES:
    return {"league": league, "would_fetch": False, "reason": "disabled"}
if league not in LEAGUES:
    return {"error": f"unknown league {league!r}; choose from {list(LEAGUES)}"}
```

- [ ] **Step 7: Update main prompt sports wording**

In `backend/agent/graph/agent.py`, change the sports tool descriptions and rule to list only NBA, Formula-One, Premier-League, Champions-League, and Ambient. The rule should say:

```text
- For live sports questions about NBA, Formula One, Premier League, Champions League, or notable Ambient events, route through the sports specialist path or call fetch_sports_if_curious with the matching enabled league. UFC and boxing are disabled unless the user explicitly asks to re-enable them in a future build.
```

- [ ] **Step 8: Run importer tests and verify pass**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_sports_importer.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```powershell
git add scripts/import_sports_snapshots.py scripts/seed_sports_folder.py backend/agent/tools/sports_curiosity.py backend/agent/graph/agent.py backend/tests/test_sports_importer.py
git commit -m "fix: normalize enabled sports ingestion"
```

## Task 2: Add Specialist Response Contract

**Files:**
- Create: `backend/agent/agents/__init__.py`
- Create: `backend/agent/agents/base.py`
- Create: `backend/tests/test_specialist_agents.py`

- [ ] **Step 1: Write failing schema tests**

Create `backend/tests/test_specialist_agents.py` with:

```python
from agent.agents.base import MemoryProposal, SpecialistResponse, SpecialistSource


def test_specialist_response_defaults_to_empty_sources_and_memory_proposals():
    response = SpecialistResponse(agent="SportsAgent", status="answered", summary="Knicks are in the Finals.")

    assert response.agent == "SportsAgent"
    assert response.status == "answered"
    assert response.sources == []
    assert response.memory_proposals == []
    assert response.confidence == 0.0


def test_specialist_source_preserves_freshness_metadata():
    source = SpecialistSource(
        kind="vault",
        title="NBA latest",
        path_or_url="Library/Sports/NBA/latest.md",
        captured_at="2026-05-27T00:00:00+00:00",
        freshness="recent",
    )

    assert source.kind == "vault"
    assert source.freshness == "recent"


def test_memory_proposal_is_structured():
    proposal = MemoryProposal(
        scope="sports",
        claim="User follows Arsenal.",
        evidence="User repeatedly asks for Arsenal updates.",
        confidence=0.9,
    )

    assert proposal.scope == "sports"
    assert proposal.confidence == 0.9
```

- [ ] **Step 2: Run schema tests and verify they fail**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_specialist_agents.py -v
```

Expected: import error because `agent.agents` does not exist.

- [ ] **Step 3: Implement specialist schema**

Create `backend/agent/agents/base.py`:

```python
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field


SpecialistStatus = Literal["answered", "needs_fetch", "stale", "blocked", "error"]
SourceKind = Literal["vault", "web", "api", "memory"]
Freshness = Literal["live", "recent", "stale", "historical"]
MemoryScope = Literal["sports", "x", "youtube", "memory", "mcp", "shared"]


class SpecialistSource(BaseModel):
    kind: SourceKind
    title: str
    path_or_url: str
    captured_at: str = ""
    freshness: Freshness = "historical"


class MemoryProposal(BaseModel):
    scope: MemoryScope
    claim: str
    evidence: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SpecialistResponse(BaseModel):
    agent: str
    status: SpecialistStatus
    summary: str
    analysis: str = ""
    sources: list[SpecialistSource] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    memory_proposals: list[MemoryProposal] = Field(default_factory=list)


class SpecialistAgent(Protocol):
    name: str

    def can_handle(self, query: str) -> bool:
        ...

    def answer(self, query: str) -> SpecialistResponse:
        ...
```

Create `backend/agent/agents/__init__.py`:

```python
from agent.agents.base import MemoryProposal, SpecialistAgent, SpecialistResponse, SpecialistSource

__all__ = [
    "MemoryProposal",
    "SpecialistAgent",
    "SpecialistResponse",
    "SpecialistSource",
]
```

- [ ] **Step 4: Run schema tests and verify pass**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_specialist_agents.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/agents/__init__.py backend/agent/agents/base.py backend/tests/test_specialist_agents.py
git commit -m "feat: add specialist agent response contract"
```

## Task 3: Add SportsAgent

**Files:**
- Create: `backend/agent/agents/sports.py`
- Modify: `backend/tests/test_specialist_agents.py`

- [ ] **Step 1: Add failing SportsAgent tests**

Append to `backend/tests/test_specialist_agents.py`:

```python
from pathlib import Path

from agent.agents.sports import SportsAgent


def test_sports_agent_detects_enabled_sports_queries():
    agent = SportsAgent(vault_root=Path("unused"))

    assert agent.can_handle("What happened in the NBA Finals?")
    assert agent.can_handle("Give me Arsenal and Champions League updates")
    assert agent.can_handle("What is happening in F1?")
    assert not agent.can_handle("Summarize my calendar")


def test_sports_agent_blocks_disabled_sports():
    agent = SportsAgent(vault_root=Path("unused"))
    response = agent.answer("Any UFC updates?")

    assert response.status == "blocked"
    assert "disabled" in response.summary.lower()


def test_sports_agent_reads_latest_snapshot_when_present(tmp_path):
    latest = tmp_path / "Library" / "Sports" / "NBA" / "latest.md"
    latest.parent.mkdir(parents=True)
    latest.write_text(
        "---\ntype: sports_nba_latest\ncaptured_at: \"2026-05-27T00:00:00+00:00\"\n---\n\n# NBA Latest\n\nKnicks await OKC or Spurs.\n",
        encoding="utf-8",
    )

    agent = SportsAgent(vault_root=tmp_path)
    response = agent.answer("NBA update")

    assert response.status == "answered"
    assert "Knicks" in response.summary
    assert response.sources[0].path_or_url == "Library/Sports/NBA/latest.md"
    assert response.memory_proposals[0].scope == "sports"
```

- [ ] **Step 2: Run SportsAgent tests and verify fail**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_specialist_agents.py -v
```

Expected: import error for `agent.agents.sports`.

- [ ] **Step 3: Implement SportsAgent**

Create `backend/agent/agents/sports.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse, SpecialistSource


ENABLED_LEAGUE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "NBA": ("nba", "basketball", "knicks", "thunder", "spurs", "finals", "playoffs"),
    "Formula-One": ("f1", "formula one", "formula 1", "grand prix", "monaco", "verstappen", "hamilton", "piastri", "antonelli"),
    "Premier-League": ("premier league", "epl", "arsenal", "man city", "liverpool", "chelsea"),
    "Champions-League": ("champions league", "ucl", "arsenal", "psg", "real madrid", "bayern"),
    "Ambient": ("sinner", "alcaraz", "djokovic", "el clasico", "grand slam"),
}

DISABLED_KEYWORDS = ("ufc", "mma", "boxing", "fight card", "octagon")


class SportsAgent:
    name = "SportsAgent"

    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    def can_handle(self, query: str) -> bool:
        text = query.casefold()
        return any(keyword in text for keywords in ENABLED_LEAGUE_KEYWORDS.values() for keyword in keywords) or any(
            keyword in text for keyword in DISABLED_KEYWORDS
        )

    def answer(self, query: str) -> SpecialistResponse:
        disabled = self._disabled_match(query)
        if disabled:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary=f"{disabled} is disabled for now. Enabled sports are NBA, Formula One, Premier League, Champions League, and Ambient.",
                confidence=1.0,
            )

        league = self._pick_league(query)
        if league is None:
            return SpecialistResponse(agent=self.name, status="needs_fetch", summary="No enabled sports league matched this query.", confidence=0.2)

        latest_path = self.vault_root / "Library" / "Sports" / league / "latest.md"
        if not latest_path.exists():
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary=f"No local {league} snapshot exists yet.",
                analysis="The daemon or on-demand fetch should refresh this league before Vellum answers with live details.",
                confidence=0.3,
            )

        text = latest_path.read_text(encoding="utf-8", errors="replace")
        summary = self._summarize_latest(text, league)
        rel_path = latest_path.relative_to(self.vault_root).as_posix()
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis=f"Used the latest local {league} feed. Vellum should fetch again if the user needs live minute-by-minute certainty.",
            sources=[
                SpecialistSource(
                    kind="vault",
                    title=f"{league} latest",
                    path_or_url=rel_path,
                    captured_at=self._captured_at(text),
                    freshness="recent",
                )
            ],
            confidence=0.75,
            memory_proposals=[
                MemoryProposal(
                    scope="sports",
                    claim=f"User asked about {league}.",
                    evidence=f"Query matched {league} sports keywords.",
                    confidence=0.6,
                )
            ],
        )

    def _pick_league(self, query: str) -> str | None:
        text = query.casefold()
        for league, keywords in ENABLED_LEAGUE_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return league
        return None

    def _disabled_match(self, query: str) -> str | None:
        text = query.casefold()
        if "ufc" in text or "mma" in text or "octagon" in text:
            return "UFC"
        if "boxing" in text or "fight card" in text:
            return "Boxing"
        return None

    def _summarize_latest(self, text: str, league: str) -> str:
        body_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("---")]
        useful = [line for line in body_lines if not line.startswith("type:") and not line.startswith("captured_at:")]
        if not useful:
            return f"{league} latest feed exists but has no readable snapshot content."
        joined = " ".join(useful)
        return re.sub(r"\s+", " ", joined)[:500]

    def _captured_at(self, text: str) -> str:
        match = re.search(r'^captured_at:\s*"?([^"\n]+)"?', text, re.MULTILINE)
        return match.group(1).strip() if match else ""
```

- [ ] **Step 4: Export SportsAgent**

Update `backend/agent/agents/__init__.py`:

```python
from agent.agents.base import MemoryProposal, SpecialistAgent, SpecialistResponse, SpecialistSource
from agent.agents.sports import SportsAgent

__all__ = [
    "MemoryProposal",
    "SpecialistAgent",
    "SpecialistResponse",
    "SpecialistSource",
    "SportsAgent",
]
```

- [ ] **Step 5: Run SportsAgent tests and verify pass**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_specialist_agents.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/agent/agents/__init__.py backend/agent/agents/sports.py backend/tests/test_specialist_agents.py
git commit -m "feat: add sports specialist agent"
```

## Task 4: Add Router and Specialist Stubs

**Files:**
- Create: `backend/agent/agents/router.py`
- Create: `backend/agent/agents/x_agent.py`
- Create: `backend/agent/agents/youtube.py`
- Create: `backend/agent/agents/memory_agent.py`
- Modify: `backend/tests/test_specialist_agents.py`

- [ ] **Step 1: Add failing router tests**

Append to `backend/tests/test_specialist_agents.py`:

```python
from agent.agents.router import SpecialistRouter


def test_router_routes_sports_to_sports_agent(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)
    route = router.route("Give me NBA updates")

    assert route.agent_name == "SportsAgent"
    assert route.should_delegate is True


def test_router_keeps_general_queries_with_vellum(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)
    route = router.route("Draft a polite email")

    assert route.agent_name == "VellumAgent"
    assert route.should_delegate is False


def test_x_and_youtube_stubs_are_contract_compatible(tmp_path):
    router = SpecialistRouter(vault_root=tmp_path)

    assert router.route("What did AlexHormozi post on X?").agent_name == "XAgent"
    assert router.route("Summarize the latest YouTube videos").agent_name == "YoutubeAgent"
```

- [ ] **Step 2: Run router tests and verify fail**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_specialist_agents.py -v
```

Expected: import error for `agent.agents.router`.

- [ ] **Step 3: Implement XAgent stub**

Create `backend/agent/agents/x_agent.py`:

```python
from __future__ import annotations

from agent.agents.base import SpecialistResponse


class XAgent:
    name = "XAgent"
    KEYWORDS = (" x ", "twitter", "tweet", "tweets", "post on x", "latest-50")

    def can_handle(self, query: str) -> bool:
        text = f" {query.casefold()} "
        return any(keyword in text for keyword in self.KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="needs_fetch",
            summary="XAgent routing is available, but full X specialist execution is deferred until the sports vertical slice is stable.",
            confidence=0.4,
        )
```

- [ ] **Step 4: Implement YoutubeAgent stub**

Create `backend/agent/agents/youtube.py`:

```python
from __future__ import annotations

from agent.agents.base import SpecialistResponse


class YoutubeAgent:
    name = "YoutubeAgent"
    KEYWORDS = ("youtube", "video", "channel", "transcript")

    def can_handle(self, query: str) -> bool:
        text = query.casefold()
        return any(keyword in text for keyword in self.KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="needs_fetch",
            summary="YoutubeAgent routing is available, but full YouTube specialist execution is deferred until the sports vertical slice is stable.",
            confidence=0.4,
        )
```

- [ ] **Step 5: Implement MemoryAgent stub**

Create `backend/agent/agents/memory_agent.py`:

```python
from __future__ import annotations

from agent.agents.base import MemoryProposal, SpecialistResponse


class MemoryAgent:
    name = "MemoryAgent"

    def can_handle(self, query: str) -> bool:
        text = query.casefold()
        return "memory" in text or "remember" in text or "preference" in text

    def answer(self, query: str) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="MemoryAgent can receive memory proposals, but this first slice does not mutate shared memory directly.",
            confidence=0.6,
        )

    def review_proposals(self, proposals: list[MemoryProposal]) -> list[MemoryProposal]:
        return [proposal for proposal in proposals if proposal.confidence >= 0.75]
```

- [ ] **Step 6: Implement SpecialistRouter**

Create `backend/agent/agents/router.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.agents.sports import SportsAgent
from agent.agents.x_agent import XAgent
from agent.agents.youtube import YoutubeAgent


@dataclass(frozen=True)
class RouteDecision:
    agent_name: str
    should_delegate: bool
    reason: str


class SpecialistRouter:
    def __init__(self, vault_root: Path):
        self.agents = [
            SportsAgent(vault_root=vault_root),
            XAgent(),
            YoutubeAgent(),
        ]

    def route(self, query: str) -> RouteDecision:
        for agent in self.agents:
            if agent.can_handle(query):
                return RouteDecision(agent_name=agent.name, should_delegate=True, reason=f"matched {agent.name}")
        return RouteDecision(agent_name="VellumAgent", should_delegate=False, reason="general-purpose query")
```

- [ ] **Step 7: Export router and stubs**

Update `backend/agent/agents/__init__.py`:

```python
from agent.agents.base import MemoryProposal, SpecialistAgent, SpecialistResponse, SpecialistSource
from agent.agents.memory_agent import MemoryAgent
from agent.agents.router import RouteDecision, SpecialistRouter
from agent.agents.sports import SportsAgent
from agent.agents.x_agent import XAgent
from agent.agents.youtube import YoutubeAgent

__all__ = [
    "MemoryAgent",
    "MemoryProposal",
    "RouteDecision",
    "SpecialistAgent",
    "SpecialistResponse",
    "SpecialistRouter",
    "SpecialistSource",
    "SportsAgent",
    "XAgent",
    "YoutubeAgent",
]
```

- [ ] **Step 8: Run router tests and verify pass**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_specialist_agents.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```powershell
git add backend/agent/agents backend/tests/test_specialist_agents.py
git commit -m "feat: add specialist routing stubs"
```

## Task 5: Add Skill-Driven Specialist Routing

**Files:**
- Create: `backend/agent/agents/skill_router.py`
- Modify: `backend/agent/agents/router.py`
- Create: `.skills/active/skill-route-sports-agent-v1.json`
- Create: `backend/tests/test_skill_driven_routing.py`

- [ ] **Step 1: Write failing skill-routing tests**

Create `backend/tests/test_skill_driven_routing.py`:

```python
import json
from pathlib import Path

from agent.agents.skill_router import SkillRoute, SkillRouteResolver
from agent.memory.skills import SkillStore


def write_skill(root: Path, payload: dict):
    active = root / "active"
    active.mkdir(parents=True)
    (active / f"{payload['id']}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_skill_route_resolver_routes_matching_skill(tmp_path):
    write_skill(
        tmp_path,
        {
            "id": "skill-route-sports-agent-v1",
            "name": "Route sports questions to SportsAgent",
            "trigger": ["NBA", "Formula One", "Arsenal", "Champions League"],
            "confidence_threshold": 0.25,
            "route_to_agent": "SportsAgent",
            "instructions": "Consult SportsAgent before answering.",
        },
    )
    resolver = SkillRouteResolver(SkillStore(root=tmp_path))

    route = resolver.resolve("Give me Arsenal and Champions League updates")

    assert route == SkillRoute(agent_name="SportsAgent", skill_id="skill-route-sports-agent-v1")


def test_skill_route_resolver_respects_negative_trigger(tmp_path):
    write_skill(
        tmp_path,
        {
            "id": "skill-route-sports-agent-v1",
            "name": "Route sports questions to SportsAgent",
            "trigger": ["sports", "UFC"],
            "negative_trigger": ["UFC"],
            "confidence_threshold": 0.25,
            "route_to_agent": "SportsAgent",
            "instructions": "Consult SportsAgent before answering.",
        },
    )
    resolver = SkillRouteResolver(SkillStore(root=tmp_path))

    assert resolver.resolve("Any UFC updates?") is None
```

- [ ] **Step 2: Run skill-routing tests and verify fail**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_skill_driven_routing.py -v
```

Expected: import error because `agent.agents.skill_router` does not exist.

- [ ] **Step 3: Implement skill route resolver**

Create `backend/agent/agents/skill_router.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from agent.memory.skills import SkillStore


@dataclass(frozen=True)
class SkillRoute:
    agent_name: str
    skill_id: str


class SkillRouteResolver:
    def __init__(self, skill_store: SkillStore | None = None):
        self.skill_store = skill_store or SkillStore()

    def resolve(self, query: str) -> SkillRoute | None:
        for skill in self.skill_store.matching_skills(query):
            agent_name = skill.get("route_to_agent")
            if isinstance(agent_name, str) and agent_name:
                return SkillRoute(agent_name=agent_name, skill_id=str(skill.get("id", "")))
        return None
```

- [ ] **Step 4: Update router to prefer skill routes**

Modify `backend/agent/agents/router.py` so `SpecialistRouter` accepts an optional resolver:

```python
from agent.agents.skill_router import SkillRouteResolver
```

and update the class:

```python
class SpecialistRouter:
    def __init__(self, vault_root: Path, skill_route_resolver: SkillRouteResolver | None = None):
        self.skill_route_resolver = skill_route_resolver or SkillRouteResolver()
        self.agents = [
            SportsAgent(vault_root=vault_root),
            XAgent(),
            YoutubeAgent(),
        ]

    def route(self, query: str) -> RouteDecision:
        skill_route = self.skill_route_resolver.resolve(query)
        if skill_route is not None:
            return RouteDecision(
                agent_name=skill_route.agent_name,
                should_delegate=True,
                reason=f"matched routing skill {skill_route.skill_id}",
            )
        for agent in self.agents:
            if agent.can_handle(query):
                return RouteDecision(agent_name=agent.name, should_delegate=True, reason=f"matched {agent.name}")
        return RouteDecision(agent_name="VellumAgent", should_delegate=False, reason="general-purpose query")
```

- [ ] **Step 5: Add active runtime sports routing skill**

Create `.skills/active/skill-route-sports-agent-v1.json`:

```json
{
  "id": "skill-route-sports-agent-v1",
  "name": "Route sports questions to SportsAgent",
  "trigger": [
    "sports",
    "NBA",
    "basketball",
    "Formula One",
    "Formula 1",
    "F1",
    "Arsenal",
    "Premier League",
    "Champions League",
    "UCL"
  ],
  "negative_trigger": [
    "UFC",
    "boxing"
  ],
  "confidence_threshold": 0.25,
  "route_to_agent": "SportsAgent",
  "instructions": "For enabled sports questions, consult SportsAgent before answering. Vellum remains the final responder. UFC and boxing are disabled unless explicitly re-enabled in a future build.",
  "citation_style": "source links or vault paths when available",
  "output_format": "current status first, then key events, analysis, and freshness caveat",
  "created": "2026-05-27",
  "approved": "2026-05-27",
  "use_count": 0,
  "last_used": ""
}
```

- [ ] **Step 6: Run skill-routing tests and verify pass**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_skill_driven_routing.py tests/test_specialist_agents.py -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add .skills/active/skill-route-sports-agent-v1.json backend/agent/agents/router.py backend/agent/agents/skill_router.py backend/tests/test_skill_driven_routing.py
git commit -m "feat: route specialists through active skills"
```

## Task 6: Add Specialist Orchestrator Guardrails

**Files:**
- Create: `backend/agent/agents/orchestrator.py`
- Create: `backend/tests/test_specialist_orchestrator.py`

- [ ] **Step 1: Write failing orchestrator tests**

Create `backend/tests/test_specialist_orchestrator.py`:

```python
from agent.agents.base import SpecialistResponse
from agent.agents.orchestrator import SpecialistOrchestrator


class FakeAgent:
    name = "FakeAgent"

    def __init__(self, can_handle=True):
        self.calls = 0
        self._can_handle = can_handle

    def can_handle(self, query):
        return self._can_handle

    def answer(self, query):
        self.calls += 1
        return SpecialistResponse(agent=self.name, status="answered", summary=f"handled {query}", confidence=0.8)


def test_orchestrator_delegates_to_first_matching_agent():
    first = FakeAgent(can_handle=True)
    second = FakeAgent(can_handle=True)
    orchestrator = SpecialistOrchestrator([first, second], max_depth=1, max_concurrency=1)

    result = orchestrator.delegate("sports update")

    assert result.agent == "FakeAgent"
    assert result.summary == "handled sports update"
    assert first.calls == 1
    assert second.calls == 0


def test_orchestrator_returns_blocked_when_depth_exceeded():
    agent = FakeAgent(can_handle=True)
    orchestrator = SpecialistOrchestrator([agent], max_depth=1, max_concurrency=1)

    result = orchestrator.delegate("sports update", depth=1)

    assert result.status == "blocked"
    assert "depth" in result.summary.lower()
    assert agent.calls == 0


def test_orchestrator_returns_needs_fetch_when_no_agent_matches():
    agent = FakeAgent(can_handle=False)
    orchestrator = SpecialistOrchestrator([agent], max_depth=1, max_concurrency=1)

    result = orchestrator.delegate("general question")

    assert result.agent == "VellumAgent"
    assert result.status == "needs_fetch"
```

- [ ] **Step 2: Run orchestrator tests and verify fail**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_specialist_orchestrator.py -v
```

Expected: import error because `agent.agents.orchestrator` does not exist.

- [ ] **Step 3: Implement specialist orchestrator**

Create `backend/agent/agents/orchestrator.py`:

```python
from __future__ import annotations

from collections.abc import Iterable

from agent.agents.base import SpecialistAgent, SpecialistResponse


class SpecialistOrchestrator:
    """Small parent-owned delegation helper.

    Mirrors Codex's useful subagent constraints for Vellum runtime agents:
    explicit parent delegation, depth cap, and one consolidated specialist
    response returned to Vellum.
    """

    def __init__(self, agents: Iterable[SpecialistAgent], max_depth: int = 1, max_concurrency: int = 1):
        self.agents = list(agents)
        self.max_depth = max_depth
        self.max_concurrency = max_concurrency

    def delegate(self, query: str, depth: int = 0) -> SpecialistResponse:
        if depth >= self.max_depth:
            return SpecialistResponse(
                agent="VellumAgent",
                status="blocked",
                summary="Specialist delegation depth limit reached.",
                confidence=1.0,
            )

        for agent in self.agents[: self.max_concurrency]:
            if agent.can_handle(query):
                return agent.answer(query)

        return SpecialistResponse(
            agent="VellumAgent",
            status="needs_fetch",
            summary="No specialist matched this query; Vellum should answer directly.",
            confidence=0.5,
        )
```

- [ ] **Step 4: Export orchestrator**

Update `backend/agent/agents/__init__.py` to include:

```python
from agent.agents.orchestrator import SpecialistOrchestrator
```

and add `"SpecialistOrchestrator"` to `__all__`.

- [ ] **Step 5: Run orchestrator tests and verify pass**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_specialist_orchestrator.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/agent/agents/__init__.py backend/agent/agents/orchestrator.py backend/tests/test_specialist_orchestrator.py
git commit -m "feat: add specialist orchestration guardrails"
```

## Task 7: Add Daemon Sports Loop

**Files:**
- Create: `backend/agent/daemon/__init__.py`
- Create: `backend/agent/daemon/loops/__init__.py`
- Create: `backend/agent/daemon/loops/sports.py`
- Create: `backend/agent/daemon/main.py`
- Modify: `backend/agent/config.py`
- Modify: `backend/tests/test_sports_daemon.py`

- [ ] **Step 1: Write failing daemon tests**

Create `backend/tests/test_sports_daemon.py`:

```python
import json
from pathlib import Path

from agent.daemon.loops.sports import SportsDaemonLoop


class FakeCuriosity:
    def __init__(self):
        self.checked = []
        self.fetched = []

    def should_fetch(self, league):
        self.checked.append(league)
        return {"league": league, "would_fetch": league == "NBA", "score": 0.9, "threshold": 0.65, "reason": "above_threshold"}

    def fetch(self, league, curiosity_reason):
        self.fetched.append((league, curiosity_reason))
        return {"fetched": True, "result": {"league": league, "path": "Library/Sports/NBA/snapshots/2026/test.md"}}


def test_sports_daemon_tick_fetches_only_enabled_league(tmp_path):
    curiosity = FakeCuriosity()
    loop = SportsDaemonLoop(
        vault_root=tmp_path,
        curiosity=curiosity,
        enabled_leagues=("NBA", "Formula-One"),
        dry_run=False,
    )

    result = loop.tick()

    assert result["checked"] == ["NBA", "Formula-One"]
    assert result["fetched"] == ["NBA"]
    assert curiosity.fetched == [("NBA", "daemon sports_loop curiosity tick")]


def test_sports_daemon_dry_run_does_not_fetch(tmp_path):
    curiosity = FakeCuriosity()
    loop = SportsDaemonLoop(vault_root=tmp_path, curiosity=curiosity, enabled_leagues=("NBA",), dry_run=True)

    result = loop.tick()

    assert result["checked"] == ["NBA"]
    assert result["fetched"] == []
    assert curiosity.fetched == []


def test_sports_daemon_writes_tick_log(tmp_path):
    curiosity = FakeCuriosity()
    loop = SportsDaemonLoop(vault_root=tmp_path, curiosity=curiosity, enabled_leagues=("NBA",), dry_run=True)

    loop.tick()

    log_path = tmp_path / "Agent" / "Memories" / "Daemon" / "sports-loop-last.json"
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["loop"] == "sports"
    assert payload["dry_run"] is True
```

- [ ] **Step 2: Run daemon tests and verify fail**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_sports_daemon.py -v
```

Expected: import error because daemon modules do not exist.

- [ ] **Step 3: Add daemon settings**

In `backend/agent/config.py`, add fields near existing scheduler settings:

```python
    enable_vellum_daemon: bool = Field(default=False, alias="ENABLE_VELLUM_DAEMON")
    daemon_sports_interval_seconds: int = Field(default=1800, alias="DAEMON_SPORTS_INTERVAL_SECONDS")
    daemon_sports_enabled_leagues: str = Field(
        default="NBA,Formula-One,Premier-League,Champions-League,Ambient",
        alias="DAEMON_SPORTS_ENABLED_LEAGUES",
    )
```

In `validate_paths_and_privacy`, add:

```python
        if self.daemon_sports_interval_seconds < 60:
            raise ValueError("DAEMON_SPORTS_INTERVAL_SECONDS must be at least 60.")
```

- [ ] **Step 4: Implement sports daemon loop**

Create `backend/agent/daemon/__init__.py`:

```python
"""Local daemon loops for Vellum background attention."""
```

Create `backend/agent/daemon/loops/__init__.py`:

```python
"""Daemon loop implementations."""
```

Create `backend/agent/daemon/loops/sports.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from agent.tools import sports_curiosity


class SportsCuriosityAdapter(Protocol):
    def should_fetch(self, league: str) -> dict:
        ...

    def fetch(self, league: str, curiosity_reason: str) -> dict:
        ...


class LangChainSportsCuriosity:
    def should_fetch(self, league: str) -> dict:
        return sports_curiosity.should_fetch_sports.invoke({"league": league})

    def fetch(self, league: str, curiosity_reason: str) -> dict:
        return sports_curiosity.fetch_sports_if_curious.invoke({"league": league, "curiosity_reason": curiosity_reason})


class SportsDaemonLoop:
    def __init__(
        self,
        vault_root: Path,
        curiosity: SportsCuriosityAdapter | None = None,
        enabled_leagues: tuple[str, ...] = ("NBA", "Formula-One", "Premier-League", "Champions-League", "Ambient"),
        dry_run: bool = False,
    ):
        self.vault_root = Path(vault_root)
        self.curiosity = curiosity or LangChainSportsCuriosity()
        self.enabled_leagues = enabled_leagues
        self.dry_run = dry_run

    def tick(self) -> dict:
        checked: list[str] = []
        fetched: list[str] = []
        decisions: list[dict] = []
        reason = "daemon sports_loop curiosity tick"

        for league in self.enabled_leagues:
            decision = self.curiosity.should_fetch(league)
            checked.append(league)
            decisions.append(decision)
            if decision.get("would_fetch") and not self.dry_run:
                result = self.curiosity.fetch(league, reason)
                if result.get("fetched"):
                    fetched.append(league)

        payload = {
            "loop": "sports",
            "checked": checked,
            "fetched": fetched,
            "decisions": decisions,
            "dry_run": self.dry_run,
            "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        self._write_tick_log(payload)
        return payload

    def _write_tick_log(self, payload: dict) -> None:
        path = self.vault_root / "Agent" / "Memories" / "Daemon" / "sports-loop-last.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
```

- [ ] **Step 5: Implement daemon CLI**

Create `backend/agent/daemon/main.py`:

```python
from __future__ import annotations

import argparse
import time

from agent.config import get_settings
from agent.daemon.loops.sports import SportsDaemonLoop


def parse_leagues(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def run_once(dry_run: bool = False) -> dict:
    settings = get_settings()
    loop = SportsDaemonLoop(
        vault_root=settings.obsidian_vault_path,
        enabled_leagues=parse_leagues(settings.daemon_sports_enabled_leagues),
        dry_run=dry_run,
    )
    return loop.tick()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vellum background daemon loops.")
    parser.add_argument("--once", action="store_true", help="Run one daemon tick and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate curiosity without fetching.")
    args = parser.parse_args()

    settings = get_settings()
    if args.once:
        result = run_once(dry_run=args.dry_run)
        print(result)
        return 0

    while True:
        result = run_once(dry_run=args.dry_run)
        print(result, flush=True)
        time.sleep(settings.daemon_sports_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run daemon tests and verify pass**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_sports_daemon.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/agent/config.py backend/agent/daemon backend/tests/test_sports_daemon.py
git commit -m "feat: add sports daemon loop"
```

## Task 8: Add Daemon Start/Stop Scripts and Project Script Entry

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `scripts/start-daemon.ps1`
- Create: `scripts/stop-daemon.ps1`

- [ ] **Step 1: Add console script**

In `backend/pyproject.toml`, under `[project.scripts]`, change:

```toml
personal-agent = "agent.cli:main"
```

to:

```toml
personal-agent = "agent.cli:main"
vellum-daemon = "agent.daemon.main:main"
```

- [ ] **Step 2: Add start-daemon script**

Create `scripts/start-daemon.ps1`:

```powershell
param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root ".daemon-runtime"
$PidFile = Join-Path $Runtime "daemon.pid"
$LogFile = Join-Path $Runtime "daemon.log"
$ErrFile = Join-Path $Runtime "daemon.err.log"
$StatusFile = Join-Path $Runtime "status"

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

if (Test-Path $PidFile) {
  $ExistingPid = Get-Content $PidFile -ErrorAction SilentlyContinue
  if ($ExistingPid -and (Get-Process -Id ([int]$ExistingPid) -ErrorAction SilentlyContinue)) {
    Write-Host "Vellum daemon is already running with PID $ExistingPid."
    exit 0
  }
}

$Args = @("-m", "agent.daemon.main")
if ($DryRun) {
  $Args += "--dry-run"
}

$Process = Start-Process -FilePath "python" -ArgumentList $Args -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Hidden -PassThru -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile
Set-Content -Path $PidFile -Value $Process.Id -Encoding ascii

@(
  "status=running",
  "started_at=$((Get-Date).ToUniversalTime().ToString('s'))Z",
  "pid=$($Process.Id)",
  "dry_run=$DryRun"
) | Set-Content -Path $StatusFile -Encoding ascii

Write-Host "Vellum daemon started."
Write-Host "PID: $($Process.Id)"
```

- [ ] **Step 3: Add stop-daemon script**

Create `scripts/stop-daemon.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $Root ".daemon-runtime"
$PidFile = Join-Path $Runtime "daemon.pid"
$StatusFile = Join-Path $Runtime "status"

if (-not (Test-Path $PidFile)) {
  Write-Host "Vellum daemon is not running."
  exit 0
}

$PidValue = Get-Content $PidFile -ErrorAction SilentlyContinue
if ($PidValue) {
  $Process = Get-Process -Id ([int]$PidValue) -ErrorAction SilentlyContinue
  if ($Process) {
    Stop-Process -Id $Process.Id -Force
  }
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
@(
  "status=stopped",
  "stopped_at=$((Get-Date).ToUniversalTime().ToString('s'))Z"
) | Set-Content -Path $StatusFile -Encoding ascii

Write-Host "Vellum daemon stopped."
```

- [ ] **Step 4: Verify daemon one-shot command**

Run:

```powershell
cd Vellum\backend
python -m agent.daemon.main --once --dry-run
```

Expected: prints a dict containing `'loop': 'sports'` and `'dry_run': True`.

- [ ] **Step 5: Commit**

```powershell
git add backend/pyproject.toml scripts/start-daemon.ps1 scripts/stop-daemon.ps1
git commit -m "chore: add daemon entrypoint scripts"
```

## Task 9: Integrate Router Into Main Agent Prompt Surface

**Files:**
- Modify: `backend/agent/graph/agent.py`
- Modify: `backend/tests/test_agent_prompt.py`

- [ ] **Step 1: Add failing prompt test**

In `backend/tests/test_agent_prompt.py`, add:

```python
from agent.graph.agent import VELLUM_SYSTEM_PROMPT


def test_prompt_describes_main_agent_as_router_with_specialists():
    assert "Specialist agents advise; Vellum decides" in VELLUM_SYSTEM_PROMPT
    assert "SportsAgent" in VELLUM_SYSTEM_PROMPT
    assert "XAgent" in VELLUM_SYSTEM_PROMPT
    assert "YoutubeAgent" in VELLUM_SYSTEM_PROMPT
    assert "UFC and boxing are disabled" in VELLUM_SYSTEM_PROMPT
```

- [ ] **Step 2: Run prompt test and verify fail**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_agent_prompt.py::test_prompt_describes_main_agent_as_router_with_specialists -v
```

Expected: assertion failure because prompt lacks the exact routing sentence.

- [ ] **Step 3: Update Vellum system prompt**

In `backend/agent/graph/agent.py`, add this block inside `VELLUM_SYSTEM_PROMPT` after the tool list:

```text
Specialist routing:
- Vellum is the main general-purpose agent and final responder.
- Specialist agents advise; Vellum decides.
- SportsAgent handles NBA, Formula One, Premier League, Champions League, and rare Ambient sports events.
- XAgent and YoutubeAgent are routed specialist surfaces; their first implementation may return contract-compatible stubs until full specialist loops are built.
- UFC and boxing are disabled for sports ingestion and live-update routing.
```

- [ ] **Step 4: Run prompt test and verify pass**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_agent_prompt.py::test_prompt_describes_main_agent_as_router_with_specialists -v
```

Expected: test passes.

- [ ] **Step 5: Commit**

```powershell
git add backend/agent/graph/agent.py backend/tests/test_agent_prompt.py
git commit -m "docs: describe specialist routing in prompt"
```

## Task 10: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run targeted test suite**

Run:

```powershell
cd Vellum\backend
python -m pytest tests/test_sports_importer.py tests/test_specialist_agents.py tests/test_sports_daemon.py tests/test_agent_prompt.py -v
```

Expected: all selected tests pass.

Also run:

```powershell
python -m pytest tests/test_specialist_orchestrator.py -v
```

Expected: all orchestrator guardrail tests pass.

- [ ] **Step 2: Run daemon dry-run from repo root**

Run:

```powershell
cd Vellum
.\scripts\start-daemon.ps1 -DryRun
Start-Sleep -Seconds 3
.\scripts\stop-daemon.ps1
```

Expected:

- start script prints `Vellum daemon started.`
- stop script prints `Vellum daemon stopped.`
- `.daemon-runtime/status` exists
- `Vault/Agent/Memories/Daemon/sports-loop-last.json` exists if the configured vault path points to the repo vault

- [ ] **Step 3: Inspect git status**

Run:

```powershell
git status --short
```

Expected: only unrelated pre-existing user changes remain. Files changed by this plan should be committed.
