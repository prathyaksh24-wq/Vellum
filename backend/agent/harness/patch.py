"""The harness Loader patch dialect (the DeepSeek Harness / Cordis dialect).

A composition is an ordered list of patch layers applied over the base rows:

- ``insert: [rows]`` appends rows.
- A patch with an ``id`` and no ``insert`` targets the existing row with that id.
  Supplied fields replace the row's fields; ``config`` is replaced wholesale, never
  deep-merged. A truthy ``name`` asserts the existing plugin name rather than
  renaming it.
- Non-insert patches without a nonempty ``id``, and targets that match no row, are
  reported as warnings and skipped.

A row is ``{id, name, config?, disabled?}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


_ROW_FIELDS = frozenset({"id", "name", "config", "disabled"})


class PatchError(ValueError):
    """A patch layer cannot be read as the patch dialect."""


@dataclass
class Row:
    id: str
    name: str
    config: Any = None
    disabled: bool = False
    # Where the row was inserted and which layers changed it, for inspection.
    origin: str = ""
    overridden_by: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "config": self.config,
            "disabled": self.disabled,
            "origin": self.origin,
            "overriddenBy": list(self.overridden_by),
        }


@dataclass(frozen=True)
class Layer:
    label: str
    patches: tuple[dict[str, Any], ...]


def read_layer(path: Path, label: str) -> Layer:
    if not path.is_file():
        return Layer(label, ())
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PatchError(f"{label}: invalid YAML: {exc}") from exc
    return parse_layer(data, label)


def parse_layer(data: Any, label: str) -> Layer:
    if data is None:
        return Layer(label, ())
    if not isinstance(data, list):
        raise PatchError(f"{label}: a patch file is a YAML list of patches.")
    patches: list[dict[str, Any]] = []
    for index, patch in enumerate(data):
        if not isinstance(patch, dict):
            raise PatchError(f"{label}[{index}]: each patch is a mapping.")
        if "insert" in patch:
            rows = patch["insert"]
            if not isinstance(rows, list):
                raise PatchError(f"{label}[{index}]: insert takes a list of rows.")
            for row_index, row in enumerate(rows):
                _check_row(row, f"{label}[{index}].insert[{row_index}]", insert=True)
        else:
            unknown = set(patch) - _ROW_FIELDS
            if unknown:
                raise PatchError(f"{label}[{index}]: unknown fields {sorted(unknown)}.")
        patches.append(patch)
    return Layer(label, tuple(patches))


def _check_row(row: Any, where: str, *, insert: bool) -> None:
    if not isinstance(row, dict):
        raise PatchError(f"{where}: a row is a mapping.")
    unknown = set(row) - _ROW_FIELDS
    if unknown:
        raise PatchError(f"{where}: unknown fields {sorted(unknown)}.")
    if insert:
        if not isinstance(row.get("id"), str) or not row["id"].strip():
            raise PatchError(f"{where}: an inserted row needs a nonempty id.")
        if not isinstance(row.get("name"), str) or not row["name"].strip():
            raise PatchError(f"{where}: an inserted row needs a plugin name.")
    if "disabled" in row and not isinstance(row["disabled"], (bool, type(None))):
        raise PatchError(f"{where}: disabled is true, false or null.")


def compose(layers: list[Layer]) -> tuple[list[Row], list[str]]:
    """Apply layers in order and return the rows and the warnings."""

    rows: list[Row] = []
    by_id: dict[str, Row] = {}
    warnings: list[str] = []
    for layer in layers:
        for patch in layer.patches:
            if "insert" in patch:
                for raw in patch["insert"]:
                    if raw["id"] in by_id:
                        warnings.append(f"{layer.label}: row '{raw['id']}' already exists; insert skipped.")
                        continue
                    row = Row(
                        id=raw["id"],
                        name=raw["name"],
                        config=raw.get("config"),
                        disabled=bool(raw.get("disabled") or False),
                        origin=layer.label,
                    )
                    rows.append(row)
                    by_id[row.id] = row
                continue
            target_id = patch.get("id")
            if not isinstance(target_id, str) or not target_id.strip():
                warnings.append(f"{layer.label}: a patch without insert needs an id; skipped.")
                continue
            row = by_id.get(target_id)
            if row is None:
                warnings.append(f"{layer.label}: no row '{target_id}' to patch; skipped.")
                continue
            name = patch.get("name")
            if name and name != row.name:
                warnings.append(
                    f"{layer.label}: row '{target_id}' is '{row.name}', not '{name}'; patch skipped."
                )
                continue
            if "config" in patch:
                row.config = patch["config"]
            if "disabled" in patch:
                row.disabled = bool(patch["disabled"] or False)
            row.overridden_by.append(layer.label)
    return rows, warnings


def dump_layer(patches: list[dict[str, Any]]) -> str:
    return yaml.safe_dump(patches, sort_keys=False, allow_unicode=True) if patches else ""
