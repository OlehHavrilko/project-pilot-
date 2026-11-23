"""Unit tests for the observation text renderer."""

from __future__ import annotations

from perception.render import render_ax_tree, render_snapshot


def test_render_snapshot_keeps_numbers_and_values() -> None:
    snapshot = {
        "active_window": "OBS 33.0.3",
        "elements": [
            {
                "id": 1,
                "window": "OBS 33.0.3",
                "control_type": "Window",
                "name": "OBS",
                "focused": True,
            },
            {"id": 2, "window": "OBS 33.0.3", "control_type": "Button", "name": "Начать запись"},
            {
                "id": 3,
                "window": "OBS 33.0.3",
                "control_type": "Edit",
                "name": "",
                "value": "текст",
            },
            {"id": 4, "window": "OBS 33.0.3", "control_type": "Pane", "name": "", "value": ""},
        ],
    }
    text = render_snapshot(snapshot)
    assert "[окно] OBS 33.0.3 (focused)" in text
    assert '[2]' in text and 'button "Начать запись"' in text
    assert '"текст"' in text
    assert "[4]" not in text


def test_render_ax_tree_skips_empty_and_limits() -> None:
    nodes = [
        {"id": 1, "role": "button", "name": "Вход", "value": ""},
        {"id": 2, "role": "generic", "name": "", "value": ""},
        {"id": 3, "role": "textbox", "name": "Пароль", "value": ""},
    ]
    text = render_ax_tree("Discord", nodes)
    assert "button \"Вход\"" in text
    assert "textbox \"Пароль\"" in text
    assert "[2]" not in text
