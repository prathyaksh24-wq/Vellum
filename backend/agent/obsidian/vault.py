"""Small pathlib-based Obsidian vault adapter."""

from datetime import datetime
from pathlib import Path
import re


class ObsidianVault:
    def __init__(self, vault_path: str | Path):
        self.vault_path = Path(vault_path).expanduser().resolve()

    def _safe_relative(self, relative_path: str | Path) -> Path:
        raw = str(relative_path).strip().strip("/")
        path = (self.vault_path / raw).resolve()
        if not path.is_relative_to(self.vault_path):
            raise ValueError("Path escapes Obsidian vault.")
        return path

    @property
    def root(self) -> Path:
        return self.vault_path

    def create_note(self, folder: str, title: str, content: str) -> Path:
        folder_path = self._safe_relative(folder)
        folder_path.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[^A-Za-z0-9._ -]+", "-", title).strip(" .-") or "Untitled"
        note_path = folder_path / f"{safe_title}.md"
        if note_path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            note_path = folder_path / f"{safe_title}-{stamp}.md"
        note_path.write_text(content, encoding="utf-8")
        return note_path

    def iter_markdown(self):
        yield from self.vault_path.rglob("*.md")

    def read_note(self, relative_path: str | Path) -> str:
        target = self._safe_relative(relative_path)
        if not target.exists():
            return ""
        return target.read_text(encoding="utf-8", errors="ignore")

    def append_to_note(self, relative_path: str | Path, content: str) -> None:
        target = self._safe_relative(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"\n\n{content}")

    def search(self, keyword: str, folder: str | None = None, limit: int = 10) -> list[dict]:
        folders = [folder] if folder else None
        results = self.search_notes(keyword, folders=folders, limit=limit)
        return [
            {
                "file": Path(item["metadata"]["path"]).name,
                "path": item["metadata"]["path"],
                "folder": item["metadata"]["folder"],
                "preview": item["text"][:300],
                "score": item["score"],
            }
            for item in results
        ]

    def search_notes(self, query: str, folders: list[str] | None = None, limit: int = 10) -> list[dict]:
        terms = {term.casefold() for term in re.findall(r"[A-Za-z0-9]+", query or "") if len(term) > 2}
        if not terms:
            return []

        allowed_roots = [self._safe_relative(folder) for folder in (folders or []) if folder]
        results: list[dict] = []

        for path in self.iter_markdown():
            if allowed_roots and not any(path.is_relative_to(root) for root in allowed_roots if root.exists()):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            haystack = text.casefold()
            hits = sum(1 for term in terms if term in haystack)
            if not hits:
                continue
            relative = path.relative_to(self.vault_path).as_posix()
            folder = Path(relative).parent.as_posix()
            score = hits / max(len(terms), 1)
            results.append(
                {
                    "text": text[:4000],
                    "score": min(score, 1.0),
                    "metadata": {
                        "path": relative,
                        "folder": "" if folder == "." else folder,
                    },
                }
            )

        return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]
