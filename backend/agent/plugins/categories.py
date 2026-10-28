"""Product categories for catalog browsing, independent of MCP/CLI transport."""
import re


CATEGORY_MEMBERS = {
    'CRM & Communication': (
        'asana', 'airtable', 'hubspot', 'clickup', 'slack', 'discord', 'gmail',
        'google-contacts', 'outlook', 'outlook-email', 'teams', 'zoom',
    ),
    'Productivity': (
        'linear', 'notion', 'google-workspace', 'google', 'google-drive',
        'google-calendar', 'trello', 'todoist', 'openai-templates',
        'plugin-management',
    ),
    'Developer Tools': (
        'github', 'gitmcp', 'context7', 'supabase', 'vercel', 'netlify',
        'railway', 'sentry', 'playwright', 'openai-developers',
        'matt-pocock-engineering', 'plugin-creator', 'codex-app-tools',
    ),
    'Web & Research': (
        'agent-reach', 'browser', 'brave', 'serpapi', 'exa', 'tavily',
        'firecrawl', 'apify', 'product-hunt',
    ),
    'Creativity': (
        'superdesign', '01 Superdesign', 'designly', 'design-partner',
        'product-design', 'Font Pairing: Design & Brands', 'sites',
    ),
    'Data & Analytics': ('data-analytics', 'visualize'),
    'Memory & Knowledge': ('obsidian', 'context_mode', 'memory-orchestrator'),
    'Food & Experiences': ('swiggy', 'zomato', 'district'),
    'Media & Entertainment': ('spotify', 'youtube'),
    'Automation': ('computer-use', 'unified-computer-use'),
    'Writing & Documents': ('no-ai-slop',),
    'Personalization': ('work-pets',),
    'Security': ('codex-security',),
}


def _key(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', value.casefold())


_BY_IDENTITY = {_key(member): category for category, members in CATEGORY_MEMBERS.items() for member in members}


def plugin_category(plugin_id: str, name: str, fallback: str) -> str:
    """Classify reviewed identities; retain user-defined categories and unknowns."""
    if plugin_id.startswith('custom-'):
        return fallback if fallback and fallback.casefold() not in {'mcp', 'connector', 'connectors'} else 'Personal'
    return (_BY_IDENTITY.get(_key(plugin_id)) or _BY_IDENTITY.get(_key(name))
        or ('Other' if fallback.casefold() in {'mcp', 'connectors', 'connector'} else fallback or 'Other'))
