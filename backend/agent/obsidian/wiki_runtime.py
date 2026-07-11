"""Process-wide runtime for the Obsidian knowledge wiki.

The API and LangChain tool intentionally resolve the same cached service.
Tests and local vault switches can clear that cache explicitly; normal runtime
code never creates a second wiki instance for the same process.
"""

from functools import lru_cache

from agent.config import get_settings
from agent.obsidian.wiki import KnowledgeWiki


@lru_cache(maxsize=1)
def get_knowledge_wiki() -> KnowledgeWiki:
    return KnowledgeWiki(get_settings().obsidian_vault_path)


def reset_knowledge_wiki() -> None:
    """Drop the process-wide instance for an explicit test/config reset."""
    get_knowledge_wiki.cache_clear()
