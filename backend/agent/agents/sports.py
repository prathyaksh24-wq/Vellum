from __future__ import annotations

from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse, SpecialistSource


class SportsAgent:
    name = "SportsAgent"

    _DISABLED_KEYWORDS = (
        "ufc",
        "boxing",
        "mma",
        "fight card",
        "fight night",
        "mixed martial arts",
    )
    _LEAGUE_KEYWORDS = (
        ("NBA", ("nba", "basketball", "knicks", "celtics", "lakers", "playoffs")),
        ("Formula-One", ("f1", "formula 1", "formula one", "grand prix", "monaco gp")),
        ("Champions-League", ("champions league", "ucl")),
        ("Premier-League", ("premier league", "arsenal", "epl")),
        ("Ambient", ("sports", "score", "scores", "fixture", "fixtures", "injury", "injuries")),
    )

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return self._has_disabled_keyword(lowered) or self._pick_league(lowered) is not None

    def answer(self, query: str) -> SpecialistResponse:
        lowered = query.lower()
        if self._has_disabled_keyword(lowered):
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="UFC, Boxing, MMA, and fight-card updates are disabled for SportsAgent.",
                analysis="The sports ingestion plan excludes combat-sports coverage by default.",
                confidence=0.95,
            )

        league = self._pick_league(lowered)
        if league is None:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="SportsAgent could not match this query to an enabled sports folder.",
                analysis="Ask the daemon to fetch a fresh snapshot once the target league is known.",
                confidence=0.2,
            )

        latest = self.vault_root / "Library" / "Sports" / league / "latest.md"
        if not latest.exists():
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary=f"No local {league} latest.md snapshot is available yet.",
                analysis="The sports daemon or importer should refresh this league before answering.",
                confidence=0.25,
            )

        content = latest.read_text(encoding="utf-8")
        summary = self._summarize(content)
        relative_path = latest.relative_to(self.vault_root).as_posix()

        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis=f"Read the latest stored {league} sports snapshot from the vault.",
            sources=[
                SpecialistSource(
                    kind="vault",
                    title=f"{league} latest snapshot",
                    path_or_url=relative_path,
                    captured_at=self._captured_at(content),
                    freshness="recent",
                )
            ],
            confidence=0.75,
            memory_proposals=[
                MemoryProposal(
                    scope="sports",
                    claim=f"User asked SportsAgent for {league} coverage.",
                    evidence=relative_path,
                    confidence=0.55,
                )
            ],
        )

    def _has_disabled_keyword(self, lowered_query: str) -> bool:
        return any(keyword in lowered_query for keyword in self._DISABLED_KEYWORDS)

    def _pick_league(self, lowered_query: str) -> str | None:
        for league, keywords in self._LEAGUE_KEYWORDS:
            if any(keyword in lowered_query for keyword in keywords):
                return league
        return None

    def _summarize(self, content: str) -> str:
        body = self._strip_frontmatter(content)
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if not lines:
            return "Latest sports snapshot is present but empty."
        return " ".join(lines)[:800]

    def _strip_frontmatter(self, content: str) -> str:
        if not content.startswith("---"):
            return content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return content
        return parts[2].strip()

    def _captured_at(self, content: str) -> str:
        if not content.startswith("---"):
            return ""
        frontmatter = content.split("---", 2)[1]
        for line in frontmatter.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() == "captured_at":
                return value.strip().strip('"').strip("'")
        return ""
