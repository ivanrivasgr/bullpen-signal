from __future__ import annotations

import json
from pathlib import Path


def _load_schema(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _field_type(schema: dict, field_name: str):
    for field in schema["fields"]:
        if field["name"] == field_name:
            return field["type"]
    raise AssertionError(f"field not found: {field_name}")


def test_pitch_half_inning_is_string_for_flink_sql_compatibility() -> None:
    schema = _load_schema("streaming/schemas/pitch_event.avsc")

    assert _field_type(schema, "inning_topbot") == "string"


def test_game_state_enums_are_strings_for_flink_sql_compatibility() -> None:
    schema = _load_schema("streaming/schemas/game_state_event.avsc")

    assert _field_type(schema, "inning_topbot") == "string"
    assert _field_type(schema, "event_type") == "string"
