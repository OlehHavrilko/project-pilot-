"""Render UIA snapshots as the compact numbered text the models read."""

from __future__ import annotations

from typing import Any

# Control types that never carry useful information for the agent.
SKIP_TYPES = {
    "Pane",
    "Group",
    "Custom",
    "Image",
    "Separator",
    "ScrollBar",
    "Thumb",
    "TitleBar",
    "MenuBar",
    "ToolBar",
    "StatusBar",
}

# Roles that matter even without a visible name.
INTERACTIVE = {
    "Button",
    "MenuItem",
    "Edit",
    "Document",
    "CheckBox",
    "ComboBox",
    "RadioButton",
    "TabItem",
    "ListItem",
    "TreeItem",
    "Slider",
    "Hyperlink",
    "SplitButton",
    "DataItem",
    "HeaderItem",
    "Spinner",
    "Text",
}


def _clean(text: str | None, limit: int = 80) -> str:
    if not text:
        return ""
    return " ".join(text.split())[:limit]


def render_snapshot(snapshot: dict[str, Any], max_per_window: int = 40) -> str:
    windows: dict[str, list[dict[str, Any]]] = {}
    for element in snapshot.get("elements", []):
        windows.setdefault(element.get("window", ""), []).append(element)
    active = snapshot.get("active_window", "")
    lines: list[str] = []
    for title, elements in windows.items():
        if not title:
            continue
        marker = " (focused)" if title == active else ""
        lines.append(f"[окно] {title}{marker}")
        shown = 0
        for element in elements:
            control_type = element.get("control_type", "")
            name = _clean(element.get("name"))
            value = _clean(element.get("value") or "", 60)
            if control_type in SKIP_TYPES and not name and not value:
                continue
            if not name and not value and control_type not in INTERACTIVE:
                continue
            if control_type in SKIP_TYPES and not name:
                continue
            label = f"{control_type.lower()} \"{name}\"" if name else control_type.lower()
            if value:
                label += f" = \"{value}\""
            prefix = "* " if element.get("focused") else "  "
            lines.append(f"  [{element['id']}]{prefix}{label}")
            shown += 1
            if shown >= max_per_window:
                lines.append(f"  … ещё {len(elements) - shown} элементов")
                break
    if not lines:
        return "(нет доступных окон)"
    return "\n".join(lines)


def render_ax_tree(title: str, nodes: list[dict[str, Any]], max_nodes: int = 160) -> str:
    """Render an accessibility tree (CDP) in the same format."""
    lines = [f"[окно] {title}"]
    shown = 0
    for node in nodes:
        role = (node.get("role") or "").lower()
        name = _clean(node.get("name"))
        value = _clean(node.get("value") or "", 60)
        if not name and not value:
            continue
        if role in ("generic", "none", "rootwebarea", "webarea") and not name:
            continue
        label = f"{role} \"{name}\"" if name else role
        if value:
            label += f" = \"{value}\""
        lines.append(f"  [{node['id']}]  {label}")
        shown += 1
        if shown >= max_nodes:
            lines.append(f"  … ещё {len(nodes) - shown} узлов")
            break
    if len(lines) == 1:
        return f"[окно] {title}\n  (пусто)"
    return "\n".join(lines)
