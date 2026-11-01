import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.backend.schema import build_schema, is_visible, _conditions


def fields():
    schema = build_schema()
    return schema, {f["key"]: f for s in schema["sections"] for f in s["fields"]}


def test_every_fusion_parameter_is_exported():
    schema, by_key = fields()
    assert len(by_key) == 427
    # Fusion never built a widget for this key; the schema must still expose it.
    assert by_key["FaceAlignmentInterpolation"]["options"] == ["Bilinear", "Bicubic"]
    assert schema["defaults"]["face"]["MaskShowSelection"] == "swap_mask"
    assert by_key["FaceFidelityWeightDecimalSlider"]["default"] == 0.9
    assert isinstance(by_key["SimilarityThresholdSlider"]["default"], int)


def test_condition_semantics_match_fusion():
    assert _conditions({"parentToggle": "A & B", "requiredToggleValue": True}) == [
        {"toggles": ["A", "B"], "mode": "all", "value": True}]
    assert _conditions({"parentToggle": "A | B", "requiredToggleValue": True})[0]["mode"] == "any"
    # Legacy comma syntax evaluates only the last toggle in Fusion.
    assert _conditions({"parentToggle": "A, B", "requiredToggleValue": False})[0]["toggles"] == ["B"]
    multi = {"parentSelection": ["M", "R"], "requiredSelectionValue": ["Recast", "Advanced"]}
    field = {"visible_when": _conditions(multi)}
    assert is_visible(field, {"M": "Recast", "R": "Advanced"})
    assert not is_visible(field, {"M": "Recast", "R": "Simple"})


def test_exact_key_matching():
    field = {"visible_when": _conditions({"parentToggle": "FaceRestorerEnableToggle", "requiredToggleValue": True})}
    # Fusion used substring tests; a similarly named toggle must not satisfy the rule.
    assert not is_visible(field, {"FaceRestorerEnable2Toggle": True})
    assert is_visible(field, {"FaceRestorerEnableToggle": True})
