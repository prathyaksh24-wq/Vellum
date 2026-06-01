from __future__ import annotations

from typing import Any


MAX_DEPTH = 8
MAX_NODES = 250


def normalize_fake_tree(root: Any) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    lines: list[str] = []

    def walk(node: Any, depth: int) -> None:
        if depth > MAX_DEPTH or len(elements) >= MAX_NODES:
            return
        index = len(elements)
        bounds = _bounds_dict(getattr(node, "bounds", (0, 0, 0, 0)))
        item = {
            "index": index,
            "role": str(getattr(node, "control_type", "Unknown") or "Unknown"),
            "name": str(getattr(node, "name", "") or ""),
            "bounds": bounds,
        }
        elements.append(item)
        indent = "  " * depth
        name = f" name='{item['name']}'" if item["name"] else ""
        lines.append(
            f"{indent}[{index}] {item['role']}{name} "
            f"bounds={bounds['x']},{bounds['y']},{bounds['width']}x{bounds['height']}"
        )
        for child in list(getattr(node, "children", []) or []):
            walk(child, depth + 1)

    walk(root, 0)
    return {"tree": "\n".join(lines), "elements": elements}


def get_accessibility_state(hwnd: int, *, include_text: bool = True) -> dict[str, Any]:
    if not include_text:
        return {"tree": "", "elements": []}
    try:
        import comtypes.client
    except ImportError:
        return {"tree": "", "elements": [], "error": "Windows accessibility requires comtypes."}

    try:
        uia = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation")
        element = uia.ElementFromHandle(hwnd)
    except Exception as exc:
        return {"tree": "", "elements": [], "error": f"Windows accessibility failed: {exc}"}
    return _normalize_uia_element(element)


def element_center(state: dict[str, Any], element_index: int) -> tuple[int, int]:
    for element in state.get("elements", []):
        if int(element.get("index", -1)) == int(element_index):
            bounds = element["bounds"]
            return int(bounds["x"] + bounds["width"] / 2), int(bounds["y"] + bounds["height"] / 2)
    raise ValueError(f"Element index not found: {element_index}")


def _normalize_uia_element(root: Any) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    lines: list[str] = []

    def walk(node: Any, depth: int) -> None:
        if depth > MAX_DEPTH or len(elements) >= MAX_NODES:
            return
        index = len(elements)
        bounds = _uia_bounds(node)
        role = _control_type_name(getattr(node, "CurrentControlType", 0))
        name = str(getattr(node, "CurrentName", "") or "")
        item = {"index": index, "role": role, "name": name, "bounds": bounds}
        elements.append(item)
        indent = "  " * depth
        label = f" name='{name}'" if name else ""
        lines.append(
            f"{indent}[{index}] {role}{label} "
            f"bounds={bounds['x']},{bounds['y']},{bounds['width']}x{bounds['height']}"
        )
        try:
            node.GetCurrentPropertyValue
        except Exception:
            return

    walk(root, 0)
    return {"tree": "\n".join(lines), "elements": elements}


def _bounds_dict(bounds: tuple[int, int, int, int]) -> dict[str, int]:
    left, top, right, bottom = [int(value) for value in bounds]
    return {"x": left, "y": top, "width": max(0, right - left), "height": max(0, bottom - top)}


def _uia_bounds(node: Any) -> dict[str, int]:
    rect = getattr(node, "CurrentBoundingRectangle", None)
    if rect is None:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {
        "x": int(getattr(rect, "left", 0)),
        "y": int(getattr(rect, "top", 0)),
        "width": max(0, int(getattr(rect, "right", 0)) - int(getattr(rect, "left", 0))),
        "height": max(0, int(getattr(rect, "bottom", 0)) - int(getattr(rect, "top", 0))),
    }


def _control_type_name(control_type: int) -> str:
    names = {
        50032: "Window",
        50000: "Button",
        50004: "Edit",
        50005: "Hyperlink",
        50020: "Text",
        50033: "Pane",
        50036: "TitleBar",
    }
    return names.get(int(control_type or 0), f"ControlType:{control_type}")
