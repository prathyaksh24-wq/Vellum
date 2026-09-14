"""Connector plugin descriptors for Vellum."""

from agent.plugins.registry import (
    PluginRegistry,
    PluginRegistryError,
    get_plugin_registry,
    reset_plugin_registry,
)
from agent.plugins.contributions import (
    PluginActionContribution,
    PluginContribution,
    PluginContributionCatalog,
    PluginContributionError,
    PluginSurfaceContribution,
)

__all__ = [
    "PluginActionContribution",
    "PluginContribution",
    "PluginContributionCatalog",
    "PluginContributionError",
    "PluginRegistry",
    "PluginRegistryError",
    "PluginSurfaceContribution",
    "get_plugin_registry",
    "reset_plugin_registry",
]
