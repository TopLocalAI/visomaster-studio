"""Parameter schema generated from Fusion's declarative layout tables.

The layout modules remain the single source of truth for labels, defaults,
ranges and visibility rules. This module converts them to plain JSON so a
non-Qt frontend can render the same 427 controls. Widget-specific callables
(`exec_function`) are reported by name; the backend owns their side effects.
"""
from __future__ import annotations

from typing import Any

# Each table writes into either per-face parameters or global control state,
# exactly as main_ui.MainWindow wires them.
TABLES = (
    ("common", "face", "app.ui.widgets.common_layout_data", "COMMON_LAYOUT_DATA"),
    ("swapper", "face", "app.ui.widgets.swapper_layout_data", "SWAPPER_LAYOUT_DATA"),
    ("face_editor", "face", "app.ui.widgets.face_editor_layout_data", "FACE_EDITOR_LAYOUT_DATA"),
    ("denoiser", "global", "app.ui.widgets.denoiser_layout_data", "DENOISER_LAYOUT_DATA"),
    ("settings", "global", "app.ui.widgets.settings_layout_data", "SETTINGS_LAYOUT_DATA"),
)

# Values that the native window creates outside the layout tables.
EXTRA_FACE = {"MaskShowSelection": None}
EXTRA_GLOBAL = {"OutputMediaFolder": ""}


# Fusion infers widget types from key names; this key has options but no type
# suffix, so Fusion never built a control for it (always Bilinear).
KIND_OVERRIDES = {"FaceAlignmentInterpolation": "select"}


def _kind(name: str) -> str | None:
    if name in KIND_OVERRIDES:
        return KIND_OVERRIDES[name]
    # Same precedence as layout_actions.add_widgets_to_tab_layout.
    if "Toggle" in name:
        return "toggle"
    if "Selection" in name:
        return "select"
    if "DecimalSlider" in name:
        return "decimal"
    if "Slider" in name:
        return "integer"
    if "Text" in name:
        return "text"
    return None


def _call(value: Any, dfm_manager: Any) -> Any:
    # Only the DFM model selector is dynamic; it takes the DFM manager.
    if not callable(value):
        return value
    return value(dfm_manager) if dfm_manager is not None else None


def _field(name: str, data: dict, dfm_manager: Any = None) -> dict | None:
    kind = _kind(name)
    if kind is None:
        return None
    field: dict[str, Any] = {
        "key": name,
        "type": kind,
        "label": data.get("label", name),
        "help": data.get("help", ""),
        "level": int(data.get("level", 1)),
    }
    default = _call(data.get("default"), dfm_manager)
    if callable(data.get("options")):
        field["dynamic"] = "dfm_models"
    if kind == "toggle":
        field["default"] = bool(default)
    elif kind == "select":
        field["options"] = [str(o) for o in (_call(data.get("options", []), dfm_manager) or [])]
        field["default"] = "" if default is None else str(default)
    elif kind == "decimal":
        field.update(default=float(default), min=float(data["min_value"]), max=float(data["max_value"]),
                     step=float(data["step"]), decimals=int(data["decimals"]))
    elif kind == "integer":
        field.update(default=int(float(default)), min=int(float(data["min_value"])),
                     max=int(float(data["max_value"])), step=int(float(data.get("step", 1) or 1)))
    else:
        field["default"] = "" if default is None else str(default)
    conditions = _conditions(data)
    if conditions:
        field["visible_when"] = conditions
    if data.get("exec_function") is not None:
        field["effect"] = getattr(data["exec_function"], "__name__", "callable")
    return field


def _conditions(data: dict) -> list[dict]:
    """Visibility clauses, all of which must hold. Exact key matching, unlike
    Fusion's substring test, with the same AND/OR/legacy-comma semantics."""
    clauses: list[dict] = []
    parents = str(data.get("parentToggle") or "")
    if parents:
        required = bool(data.get("requiredToggleValue", True))
        if "," in parents:  # legacy syntax: only the last toggle is evaluated
            clauses.append({"toggles": [parents.split(",")[-1].strip()], "mode": "all", "value": required})
        elif "|" in parents:
            clauses.append({"toggles": [t.strip() for t in parents.split("|")], "mode": "any", "value": required})
        else:
            clauses.append({"toggles": [t.strip() for t in parents.split("&")], "mode": "all", "value": required})
    selections = data.get("parentSelection")
    if selections:
        values = data.get("requiredSelectionValue")
        selections = [selections] if isinstance(selections, str) else list(selections)
        values = [values] if not isinstance(values, (list, tuple)) else list(values)
        for key, value in zip(selections, values):
            clauses.append({"select": str(key), "equals": str(value)})
    return clauses


def is_visible(field: dict, values: dict) -> bool:
    for clause in field.get("visible_when", ()):
        if "toggles" in clause:
            states = [bool(values.get(k, False)) for k in clause["toggles"]]
            state = any(states) if clause["mode"] == "any" else all(states)
            if state != clause["value"]:
                return False
        elif str(values.get(clause["select"])) != clause["equals"]:
            return False
    return True


def build_schema(dfm_manager: Any = None) -> dict:
    import importlib

    # Load order matches main_ui; the layout tables and control_actions are mutually imported.
    importlib.import_module("app.ui.widgets.actions.common_actions")
    sections = []
    face_defaults: dict[str, Any] = {}
    global_defaults: dict[str, Any] = {}
    for namespace, scope, module_name, attr in TABLES:
        table = getattr(importlib.import_module(module_name), attr)
        for title, entries in table.items():
            fields = []
            for name, data in entries.items():
                if not isinstance(data, dict):
                    continue
                field = _field(name, data, dfm_manager)
                if field is None:
                    continue
                fields.append(field)
                (face_defaults if scope == "face" else global_defaults)[name] = field["default"]
            if fields:
                sections.append({"id": f"{namespace}:{title}", "namespace": namespace,
                                 "scope": scope, "title": title, "fields": fields})
    from app.ui.widgets.swapper_layout_data import MASK_SHOW_DEFAULT
    face_defaults.setdefault("MaskShowSelection", MASK_SHOW_DEFAULT)
    for name, value in EXTRA_GLOBAL.items():
        global_defaults.setdefault(name, value)
    return {"version": 1, "sections": sections,
            "defaults": {"face": face_defaults, "global": global_defaults}}


# Fusion side effects that manage models/trackers; safe without widgets.
RESOURCE_EFFECTS = {
    "handle_restorer_state_change", "handle_model_selection_change", "handle_landmark_state_change",
    "handle_landmark_model_selection_change", "handle_frame_enhancer_state_change",
    "handle_enhancer_model_selection_change", "handle_face_mask_state_change",
    "handle_face_expression_toggle_change", "handle_face_expression_eye_blend_toggle",
    "handle_denoiser_state_change", "handle_face_detector_tracking_reset", "change_threads_number",
    "handle_auto_mouth_toggle", "handle_ff_auto_quality_toggle", "handle_face_reaging_toggle_change",
}


def effect_for(key: str):
    """(callable, extra args) for a parameter's Fusion side effect, if it manages resources."""
    import importlib

    importlib.import_module("app.ui.widgets.actions.common_actions")
    for _, _, module_name, attr in TABLES:
        table = getattr(importlib.import_module(module_name), attr)
        for entries in table.values():
            data = entries.get(key) if isinstance(entries, dict) else None
            if isinstance(data, dict) and data.get("exec_function") is not None:
                fn = data["exec_function"]
                if getattr(fn, "__name__", "") in RESOURCE_EFFECTS:
                    return fn, list(data.get("exec_function_args", []))
                return None
    return None
