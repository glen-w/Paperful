import json

from scripts.coverage_badge import badge_from_coverage, color_for, write_badge


def test_color_bands():
    assert color_for(90) == "brightgreen"
    assert color_for(80) == "green"
    assert color_for(70) == "yellowgreen"
    assert color_for(60) == "yellow"
    assert color_for(50) == "orange"
    assert color_for(49) == "red"


def test_badge_uses_coverage_display_percent():
    badge = badge_from_coverage({"totals": {"percent_covered_display": "87"}})
    assert badge == {
        "schemaVersion": 1,
        "label": "coverage",
        "message": "87%",
        "color": "green",
    }


def test_write_badge(tmp_path):
    src = tmp_path / "coverage.json"
    dest = tmp_path / "badges" / "coverage.json"
    src.write_text(
        json.dumps({"totals": {"percent_covered_display": "91"}}),
        encoding="utf-8",
    )
    assert write_badge(src, dest)["message"] == "91%"
    assert json.loads(dest.read_text(encoding="utf-8"))["color"] == "brightgreen"
