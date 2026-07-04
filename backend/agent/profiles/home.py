from __future__ import annotations

from pathlib import Path


class AgentHomeManager:
    def __init__(self, root: str | Path = Path("data/agents")) -> None:
        self.root = Path(root)

    def ensure(self, agent_id: str) -> Path:
        home = self.root / agent_id
        for name in ("memory", "sessions", "workspace", "audit", "skills", "personalities"):
            (home / name).mkdir(parents=True, exist_ok=True)
        self._seed(home / "SOUL.md", f"# {agent_id}\n\nYou are {agent_id}, a focused Vellum specialist.\n")
        self._seed(home / "AGENTS.md", f"# {agent_id} Operating Instructions\n\nWork only within your assigned role and evidence.\n")
        self._seed(home / "personalities" / "default.md", "# Default\n\nUse the durable SOUL.md personality.\n")
        return home

    @staticmethod
    def _seed(path: Path, content: str) -> None:
        if not path.exists():
            path.write_text(content, encoding="utf-8", newline="\n")
