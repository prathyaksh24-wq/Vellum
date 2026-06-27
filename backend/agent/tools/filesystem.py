"""Filesystem tools restricted to the configured Obsidian vault."""

from pathlib import Path

from langchain_core.tools import tool

from agent.config import get_settings
from agent.mcp.filesystem_tools import run_tool as fs_run
from agent.obsidian.vault import ObsidianVault


@tool
def read_file(path: str) -> str:
    """Read a specific file from the local filesystem or Obsidian vault."""
    return fs_run({"query": path})


@tool
def list_files(directory: str = "") -> str:
    """List files in a directory within the Obsidian vault."""
    settings = get_settings()
    vault = ObsidianVault(settings.obsidian_vault_path)
    root = vault._safe_relative(directory or ".")
    if not root.exists() or not root.is_dir():
        return f"No files found in '{directory or 'vault root'}'"
    paths = sorted(path.relative_to(vault.root).as_posix() for path in root.iterdir())
    return "\n".join(f"- {path}" for path in paths) if paths else f"No files found in '{directory or 'vault root'}'"

