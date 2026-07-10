"""Process-wide runtime for the Obsidian knowledge wiki."""

from functools import lru_cache

from agent.config import get_settings
from agent.obsidian.wiki import KnowledgeWiki


@lru_cache(maxsize=1)
def get_knowledge_wiki() -> KnowledgeWiki:
    return KnowledgeWiki(get_settings().obsidian_vault_path)
