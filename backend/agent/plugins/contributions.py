"""Plugin-owned App Action and UI Surface declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.app_actions.models import AppActionContext, AppActionDefinition, UISurfaceDefinition
from agent.plugins.registry import PluginRegistry
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


Availability = Callable[[AppActionContext | None], bool]
ActionAdapter = Callable[[dict[str, Any]], dict[str, Any]]


class PluginContributionError(ValueError):
    pass


@dataclass(frozen=True)
class PluginActionContribution:
    definition: AppActionDefinition
    adapter: ActionAdapter | None = None
    availability: Availability | None = None
    allowed_agents: frozenset[str] = frozenset({"VellumAgent", "VellumUI"})


@dataclass(frozen=True)
class PluginSurfaceContribution:
    definition: UISurfaceDefinition
    availability: Availability | None = None


@dataclass(frozen=True)
class PluginContribution:
    owner: str
    actions: tuple[PluginActionContribution, ...] = ()
    surfaces: tuple[PluginSurfaceContribution, ...] = ()


@dataclass(frozen=True)
class ContributionDiagnostic:
    owner: str
    kind: str
    identifier: str
    code: str


class PluginContributionCatalog:
    """Validate declarations and project enabled contributions into App Actions."""

    def __init__(
        self,
        *,
        plugins: PluginRegistry,
        capabilities: ToolRegistry,
        reserved_action_ids: set[str] | frozenset[str] = frozenset(),
        reserved_surface_references: set[str] | frozenset[str] = frozenset(),
        control_kernel_references: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self._plugins = plugins
        self._capabilities = capabilities
        self._reserved_action_ids = frozenset(reserved_action_ids)
        self._reserved_surface_references = frozenset(reserved_surface_references)
        self._control_kernel_references = frozenset(control_kernel_references)
        self._actions: dict[str, tuple[str, PluginActionContribution]] = {}
        self._surfaces: dict[str, tuple[str, PluginSurfaceContribution]] = {}

    def register(self, contribution: PluginContribution) -> None:
        owner = contribution.owner.strip()
        if not owner or not self._plugins.contains(owner):
            raise PluginContributionError(f"Unknown contribution owner: {owner or '<empty>'}")
        declared_permissions = self._plugins.capabilities(owner)
        action_ids = [item.definition.id for item in contribution.actions]
        surface_ids = [item.definition.reference for item in contribution.surfaces]
        if len(action_ids) != len(set(action_ids)) or len(surface_ids) != len(set(surface_ids)):
            raise PluginContributionError(f"{owner} declares duplicate contribution identifiers")

        for item in contribution.actions:
            definition = item.definition
            self._validate_owner(owner, definition.owner, definition.plugin_id, definition.id)
            if item.adapter is not None and not callable(item.adapter):
                raise PluginContributionError(f"App Action adapter must be callable: {definition.id}")
            if item.availability is not None and not callable(item.availability):
                raise PluginContributionError(f"App Action availability must be callable: {definition.id}")
            if (
                definition.id in self._reserved_action_ids
                or definition.id in self._actions
                or definition.id in self._capabilities.names()
            ):
                raise PluginContributionError(f"App Action identifier is already registered: {definition.id}")
            if definition.ui_reference in self._control_kernel_references:
                raise PluginContributionError(
                    f"Plugins cannot attach App Actions to Control Kernel surface {definition.ui_reference}"
                )
            self._validate_permissions(owner, definition.id, definition.required_permissions, declared_permissions)
            try:
                CapabilityAccess(definition.access_class)
            except ValueError as exc:
                raise PluginContributionError(
                    f"Unsupported access class for {definition.id}: {definition.access_class}"
                ) from exc

        for item in contribution.surfaces:
            definition = item.definition
            self._validate_owner(owner, definition.owner, definition.plugin_id, definition.reference)
            if item.availability is not None and not callable(item.availability):
                raise PluginContributionError(f"UI Surface availability must be callable: {definition.reference}")
            if definition.control_kernel or definition.reference in self._control_kernel_references:
                raise PluginContributionError(
                    f"Plugins cannot contribute or replace Control Kernel surface {definition.reference}"
                )
            if definition.reference in self._reserved_surface_references or definition.reference in self._surfaces:
                raise PluginContributionError(
                    f"UI Surface identifier is already registered: {definition.reference}"
                )
            self._validate_permissions(owner, definition.reference, definition.required_permissions, declared_permissions)

        for item in contribution.actions:
            definition = item.definition
            self._actions[definition.id] = (owner, item)
            if item.adapter is not None:
                self._capabilities.register(CapabilityRecord(
                    name=definition.id,
                    namespace=owner,
                    access=CapabilityAccess(definition.access_class),
                    allowed_agents=item.allowed_agents,
                    stream_label=definition.title,
                    adapter=item.adapter,
                ))
        for item in contribution.surfaces:
            self._surfaces[item.definition.reference] = (owner, item)

    def action_definition(self, action_id: str) -> AppActionDefinition | None:
        record = self._actions.get(action_id)
        return record[1].definition if record else None

    def has_action(self, action_id: str) -> bool:
        return action_id in self._actions

    def action_available(self, action_id: str, context: AppActionContext | None = None) -> bool:
        record = self._actions.get(action_id)
        if record is None:
            return False
        owner, contribution = record
        return bool(
            self._plugins.is_enabled(owner)
            and contribution.adapter is not None
            and self._available(contribution.availability, context)
        )

    def actions(self, context: AppActionContext | None = None) -> list[AppActionDefinition]:
        return [
            contribution.definition
            for action_id, (_owner, contribution) in self._actions.items()
            if self.action_available(action_id, context)
        ]

    def surfaces(self, context: AppActionContext | None = None) -> list[UISurfaceDefinition]:
        return [
            contribution.definition
            for owner, contribution in self._surfaces.values()
            if self._plugins.is_enabled(owner) and self._available(contribution.availability, context)
        ]

    def diagnostics(self) -> list[ContributionDiagnostic]:
        return [
            ContributionDiagnostic(owner=owner, kind="action", identifier=action_id, code="MISSING_ACTION_ADAPTER")
            for action_id, (owner, contribution) in self._actions.items()
            if contribution.adapter is None
        ]

    def summary(
        self,
        owner: str,
        context: AppActionContext | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "app_actions": [
                {
                    **contribution.definition.model_dump(mode="json"),
                    "available": self.action_available(action_id, context),
                }
                for action_id, (action_owner, contribution) in self._actions.items()
                if action_owner == owner
            ],
            "ui_surfaces": [
                {
                    **contribution.definition.model_dump(mode="json"),
                    "available": bool(
                        self._plugins.is_enabled(surface_owner)
                        and self._available(contribution.availability, context)
                    ),
                }
                for surface_owner, contribution in self._surfaces.values()
                if surface_owner == owner
            ],
        }

    @staticmethod
    def _available(predicate: Availability | None, context: AppActionContext | None) -> bool:
        if predicate is None:
            return True
        try:
            return bool(predicate(context))
        except Exception:
            return False

    @staticmethod
    def _validate_owner(owner: str, declared_owner: str, plugin_id: str, identifier: str) -> None:
        if declared_owner != owner or plugin_id != owner:
            raise PluginContributionError(
                f"{identifier} must declare {owner} as both owner and plugin_id"
            )

    @staticmethod
    def _validate_permissions(
        owner: str,
        identifier: str,
        required: list[str],
        declared: frozenset[str],
    ) -> None:
        missing = sorted(set(required) - declared)
        if missing:
            raise PluginContributionError(
                f"{identifier} requires permissions not declared by {owner}: {', '.join(missing)}"
            )
