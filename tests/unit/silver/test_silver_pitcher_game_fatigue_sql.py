from __future__ import annotations

from tests._paths import REPO_ROOT

MODEL_SQL = (REPO_ROOT / "dbt/models/silver/silver_pitcher_game_fatigue.sql").read_text()
SILVER_YML = (REPO_ROOT / "dbt/models/silver/_silver.yml").read_text()
UNIQUE_TEST_SQL = (
    REPO_ROOT / "dbt/tests/unique_silver_pitcher_game_fatigue_natural_key.sql"
).read_text()


def _compact(value: str) -> str:
    return " ".join(value.lower().split())


def test_model_uses_table_materialization() -> None:
    assert 'materialized="table"' in _compact(MODEL_SQL)


def test_model_groups_by_game_pk_and_pitcher_id() -> None:
    compact = _compact(MODEL_SQL)
    assert "group by game_pk, pitcher_id" in compact


def test_model_filters_duplicates_before_aggregate() -> None:
    compact = _compact(MODEL_SQL)
    assert "where not is_duplicate" in compact


def test_model_threshold_buckets_match_adr_0008() -> None:
    compact = _compact(MODEL_SQL)
    assert "when count(*) < 25 then 'low'" in compact
    assert "when count(*) < 50 then 'medium'" in compact
    assert "else 'high'" in compact


def test_model_reads_silver_pitch_events_via_ref() -> None:
    compact = _compact(MODEL_SQL)
    assert '{{ ref("silver_pitch_events") }}' in compact
    assert "iceberg_scan" not in compact
    assert "s3://" not in compact


def test_dbt_contract_has_key_not_null_and_accepted_values_tests() -> None:
    compact_yml = _compact(SILVER_YML)
    compact_unique = _compact(UNIQUE_TEST_SQL)
    for column in ["game_pk", "pitcher_id", "pitch_count"]:
        assert f"name: {column}" in compact_yml
    assert "accepted_values" in compact_yml
    assert "'low'" in compact_yml
    assert "'medium'" in compact_yml
    assert "'high'" in compact_yml
    assert 'from {{ ref("silver_pitcher_game_fatigue") }}' in compact_unique
    assert "group by game_pk, pitcher_id" in compact_unique
    assert "having count(*) > 1" in compact_unique
