"""Tools for writing back to Obsidian."""

from datetime import datetime
import logging

from langchain_core.tools import tool

from agent.config import get_settings
from agent.obsidian.vault import ObsidianVault
from agent.rag.embedder import get_embedder
from agent.rag.store import get_vector_store

logger = logging.getLogger(__name__)


@tool
def create_note(title: str, content: str, folder: str = "Agent/Saved") -> str:
    """Create a new note in the Obsidian vault."""
    settings = get_settings()
    path = ObsidianVault(settings.obsidian_vault_path).create_note(folder=folder, title=title, content=content)
    try:
        get_vector_store().upsert(
            collection="obsidian_vault",
            text=content,
            embedding=get_embedder().embed(content),
            metadata={
                "folder": folder,
                "source_hash": title,
                "type": "saved_note",
                "timestamp": datetime.now().isoformat(),
                "can_send_to_llm": True,
            },
        )
    except Exception as exc:
        logger.warning("[TOOL:write] Saved note embedding skipped: %s", exc)
    return f"Note '{title}' saved to {path.relative_to(settings.obsidian_vault_path).as_posix()}"


@tool
def append_to_note(filename: str, content: str) -> str:
    """Append content to an existing Obsidian note."""
    settings = get_settings()
    ObsidianVault(settings.obsidian_vault_path).append_to_note(filename, content)
    return f"Appended to '{filename}'"


def store_qa_pair(query: str, answer: str, source: str = "agent") -> None:
    settings = get_settings()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"QA {datetime.now().strftime('%Y%m%d_%H%M%S')}"
    content = f"---\ntype: agent-response\nsource: {source}\ndate: {timestamp}\n---\n\n## Question\n{query}\n\n## Answer\n{answer}"
    ObsidianVault(settings.obsidian_vault_path).create_note(
        folder=f"{settings.agent_notes_folder}/Responses",
        title=title,
        content=content,
    )
    try:
        combined = f"Q: {query}\nA: {answer}"
        get_vector_store().upsert(
            collection="obsidian_vault",
            text=combined,
            embedding=get_embedder().embed(combined),
            metadata={
                "folder": f"{settings.agent_notes_folder}/Responses",
                "source": source,
                "timestamp": timestamp,
                "type": "qa_pair",
                "can_send_to_llm": True,
            },
        )
    except Exception as exc:
        logger.warning("[TOOL:write] Q&A embedding skipped: %s", exc)

