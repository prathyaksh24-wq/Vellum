from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HubSkillMeta:
    name: str
    description: str
    source: str
    identifier: str
    trust_level: str = "community"
    extra: dict = field(default_factory=dict)


@dataclass
class HubSkillBundle:
    name: str
    description: str
    source: str
    identifier: str
    trust_level: str
    files: dict[str, str | bytes]
    metadata: dict = field(default_factory=dict)
