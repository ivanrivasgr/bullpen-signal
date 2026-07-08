"""Build the empirical handedness-matchup calibration from Statcast parquets.

Computes league platoon splits with the delta method of The Book (Tango,
Lichtman, Dolphin -- "The Book: Playing the Percentages in Baseball",
platoon chapter): within-batter wOBA differences between opposite-side
and same-side plate appearances, weighted by the harmonic mean of the
batter's PA against each pitcher side, aggregated per batter-handedness
group. Reference values from The Book (2000-2004 data): 0.017 wOBA split
for right-handed batters, 0.027 for left-handed batters -- the emergent
check for any run of this script is that both splits come out positive
with LHB > RHB.

The within-batter delta removes the lineup-composition bias that a raw
per-bucket aggregate carries (platooning managers select who faces whom,
so bucket aggregates measure roster usage, not the matchup effect). The
harmonic-mean weighting and the separate treatment of switch hitters
follow the published practice of the delta method for platoon splits.

Mapping onto the ADR 0016 sign convention (positive = pitcher advantage)
is this project's translation of the published split, documented here:
each group's split is centered on the league-neutral baseline, so the
same-side bucket gets +split/2 and the opposite-side bucket -split/2.
Switch hitters bat opposite by construction; their delta (wOBA vs RHP
minus wOBA vs LHP) is centered the same way onto R_vs_S / L_vs_S. No
magnitude is invented: every map value is a measured split divided
symmetrically.

Two outputs from the same run, so they cannot drift:
- the seed CSV (--out): the measured buckets only, with sample sizes and
  provenance, for the dbt audit trail;
- the runtime module (--module-out, written only when the flag is passed,
  on the full-season run): the complete map the shared signal core
  imports, extending the measured buckets to the switch-pitcher entries
  (S_vs_R mirrors R_vs_R, S_vs_L mirrors L_vs_L, S_vs_S neutral) by the
  same reasoning the original placeholder documented -- a switch pitcher
  picks the favorable side. Those entries are approximations, not
  calibrated values, and the generated module says so.

Statcast populates woba_value / woba_denom on the pitch that ends each
plate appearance, so SUM(woba_value) / SUM(woba_denom) counts each PA
exactly once. Batter groups (L / R / S) come from the player_handedness
seed; batters missing from the seed fall back to their observed stand
profile (both stands seen -> S) and are counted and reported -- if that
count is not zero on a full-season pull, regenerate the handedness seed
from the same parquets first.

Volume standard (docs/phase3/validation_2026_06_11_multiday.md): matchup
magnitudes only carry weight at season scale. Partial-month runs validate
the pipeline and the emergent platoon structure; the map that lands in
the signal must come from a full-season pull. The default output path is
therefore under data/processed/ (untracked); write to dbt/seeds/ and pass
--module-out only when the input is the full-season pull.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import duckdb

DEFAULT_SEED = "dbt/seeds/player_handedness.csv"
DEFAULT_OUT = "data/processed/matchup_calibration.csv"

# Reference splits from The Book (2000-2004 data), for the emergent check.
BOOK_REFERENCE = {"R": 0.017, "L": 0.027}

SETUP_VIEWS = """
CREATE TEMP VIEW pa AS
SELECT
    p_throws,
    stand,
    CAST(batter AS BIGINT) AS batter_id,
    woba_value,
    woba_denom
FROM read_parquet({parquets})
WHERE woba_denom IS NOT NULL
  AND woba_denom > 0
  AND p_throws IN ('L', 'R')
  AND stand IN ('L', 'R');

CREATE TEMP VIEW batter_group AS
WITH batter_hand AS (
    SELECT CAST(player_id AS BIGINT) AS player_id, hand
    FROM read_csv({seed}, header = true)
    WHERE role = 'batter'
),

stand_profile AS (
    SELECT
        batter_id,
        COUNT(DISTINCT stand) AS n_stands,
        MAX(stand) AS only_stand
    FROM pa
    GROUP BY batter_id
)

SELECT
    sp.batter_id,
    COALESCE(
        bh.hand,
        CASE WHEN sp.n_stands > 1 THEN 'S' ELSE sp.only_stand END
    ) AS grp,
    (bh.player_id IS NULL) AS seed_unmatched
FROM stand_profile AS sp
LEFT JOIN batter_hand AS bh ON bh.player_id = sp.batter_id;

CREATE TEMP VIEW pivoted AS
WITH per_side AS (
    SELECT
        batter_id,
        p_throws AS side,
        SUM(woba_value) AS woba_sum,
        SUM(woba_denom) AS n_pa
    FROM pa
    GROUP BY batter_id, p_throws
)

SELECT
    batter_id,
    SUM(CASE WHEN side = 'R' THEN n_pa END) AS pa_r,
    SUM(CASE WHEN side = 'R' THEN woba_sum END) AS ws_r,
    SUM(CASE WHEN side = 'L' THEN n_pa END) AS pa_l,
    SUM(CASE WHEN side = 'L' THEN woba_sum END) AS ws_l
FROM per_side
GROUP BY batter_id;
"""

SPLITS_QUERY = """
WITH eligible AS (
    SELECT
        bg.grp,
        2.0 * pv.pa_r * pv.pa_l / (pv.pa_r + pv.pa_l) AS w,
        CASE bg.grp
            WHEN 'R' THEN (pv.ws_l / pv.pa_l) - (pv.ws_r / pv.pa_r)
            WHEN 'L' THEN (pv.ws_r / pv.pa_r) - (pv.ws_l / pv.pa_l)
            ELSE (pv.ws_r / pv.pa_r) - (pv.ws_l / pv.pa_l)
        END AS delta
    FROM pivoted AS pv
    JOIN batter_group AS bg USING (batter_id)
    WHERE pv.pa_r > 0 AND pv.pa_l > 0
)

SELECT
    grp,
    COUNT(*) AS n_batters,
    SUM(w) AS harmonic_pa,
    SUM(w * delta) / SUM(w) AS split
FROM eligible
GROUP BY grp
ORDER BY grp
"""

BASELINE_QUERY = "SELECT SUM(woba_value) / SUM(woba_denom), SUM(woba_denom) FROM pa"

UNMATCHED_QUERY = """
SELECT COALESCE(SUM(pa.woba_denom), 0)
FROM pa
JOIN batter_group AS bg ON bg.batter_id = pa.batter_id
WHERE bg.seed_unmatched
"""

ONE_SIDED_QUERY = """
SELECT COUNT(*), COALESCE(SUM(COALESCE(pa_r, 0) + COALESCE(pa_l, 0)), 0)
FROM pivoted
WHERE pa_r IS NULL OR pa_l IS NULL
"""

RANGE_QUERY = """
SELECT MIN(game_date), MAX(game_date), COUNT(*)
FROM read_parquet({parquets})
"""

MODULE_DOCSTRING = '''"""Calibrated handedness-matchup magnitudes. GENERATED FILE -- DO NOT EDIT.

Generated by infra/data_prep/build_matchup_calibration.py. Audit trail
(per-bucket splits, sample sizes, league baseline) lives in
dbt/seeds/matchup_calibration.csv, produced by the same run. Data window:
{date_min} .. {date_max}, {total_pa} plate appearances. Sign convention
per ADR 0016: positive = pitcher advantage.

The switch-pitcher entries (S_vs_R, S_vs_L, S_vs_S) had no season data
and are NOT calibrated: they extend the measured map by the reasoning
the original placeholder documented -- a switch pitcher picks the
favorable side, so S_vs_R mirrors R_vs_R and S_vs_L mirrors L_vs_L,
with S_vs_S neutral. Regenerate this module by re-running the generator
with --module-out; do not edit values by hand.

The map holds exactly the nine handedness buckets. It carries no None key:
an irresolvable matchup (a player absent from the handedness seed) is not
a bucket with a neutral value -- it is the absence of a computable signal,
which compute_signal_fields represents by returning None rather than a
fabricated 0.0 (ADR 0028).
"""

'''


def _sql_literal(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def _sql_path_list(paths: list[str]) -> str:
    return "[" + ", ".join(_sql_literal(p) for p in paths) + "]"


def _map_rows(splits: dict[str, tuple[int, float, float]]) -> list[list[object]]:
    """Translate group splits into map buckets per the centering documented above.

    Returns rows of (matchup, signal_value, source_group, group_split,
    n_batters, harmonic_pa). Groups absent from the input produce no rows.
    """
    rows: list[list[object]] = []
    if "R" in splits:
        n, hpa, s = splits["R"]
        rows.append(["R_vs_R", s / 2, "RHB", s, n, hpa])
        rows.append(["L_vs_R", -s / 2, "RHB", s, n, hpa])
    if "L" in splits:
        n, hpa, s = splits["L"]
        rows.append(["L_vs_L", s / 2, "LHB", s, n, hpa])
        rows.append(["R_vs_L", -s / 2, "LHB", s, n, hpa])
    if "S" in splits:
        n, hpa, s = splits["S"]
        rows.append(["R_vs_S", -s / 2, "SWITCH", s, n, hpa])
        rows.append(["L_vs_S", s / 2, "SWITCH", s, n, hpa])
    return rows


def write_runtime_module(
    rows: list[list[object]],
    date_min: object,
    date_max: object,
    total_pa: int,
    module_path: str,
) -> None:
    """Write the complete runtime map as a generated stdlib-only module.

    The measured buckets come straight from the seed rows; the
    switch-pitcher entries mirror the favorable side per the documented
    approximation. Refuses to write a partial map: if the mirrored
    sources are missing from the run, the module would be a hole, so it
    fails loudly instead.
    """
    measured = {r[0]: round(float(r[1]), 4) for r in rows}
    required = ["R_vs_R", "R_vs_L", "L_vs_R", "L_vs_L", "R_vs_S", "L_vs_S"]
    missing = [b for b in required if b not in measured]
    if missing:
        raise SystemExit(
            f"cannot write runtime module: measured buckets missing {missing}; "
            "run against the full-season pull"
        )

    ordered: list[tuple[str, float, str | None]] = [
        ("R_vs_R", measured["R_vs_R"], None),
        ("R_vs_L", measured["R_vs_L"], None),
        ("L_vs_R", measured["L_vs_R"], None),
        ("L_vs_L", measured["L_vs_L"], None),
        ("R_vs_S", measured["R_vs_S"], None),
        ("L_vs_S", measured["L_vs_S"], None),
        ("S_vs_R", measured["R_vs_R"], "uncalibrated: mirrors R_vs_R (no season data)"),
        ("S_vs_L", measured["L_vs_L"], "uncalibrated: mirrors L_vs_L (no season data)"),
        ("S_vs_S", 0.0, "uncalibrated: neutral (no season data)"),
    ]

    lines = [
        MODULE_DOCSTRING.format(date_min=date_min, date_max=date_max, total_pa=int(total_pa)),
        "from __future__ import annotations",
        "",
        "CALIBRATED_SIGNAL_VALUES: dict[str, float] = {",
    ]
    for matchup, value, note in ordered:
        comment = f"  # {note}" if note else ""
        lines.append(f'    "{matchup}": {value},{comment}')
    lines.append("}")
    lines.append("")

    out = Path(module_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"wrote {module_path} ({len(ordered)} buckets)")


def build(
    parquet_paths: list[str],
    seed_path: str,
    out_path: str,
    module_out: str | None,
) -> None:
    for p in [*parquet_paths, seed_path]:
        if not Path(p).exists():
            raise SystemExit(f"missing input: {p}")

    con = duckdb.connect()
    parquets_sql = _sql_path_list(parquet_paths)
    date_min, date_max, pitch_rows = con.execute(
        RANGE_QUERY.format(parquets=parquets_sql)
    ).fetchone()

    for stmt in SETUP_VIEWS.format(parquets=parquets_sql, seed=_sql_literal(seed_path)).split(";"):
        if stmt.strip():
            con.execute(stmt)

    league_woba, total_pa = con.execute(BASELINE_QUERY).fetchone()
    if not total_pa:
        raise SystemExit("no plate appearances found in input; nothing to calibrate")
    unmatched_pa = con.execute(UNMATCHED_QUERY).fetchone()[0]
    one_sided_batters, one_sided_pa = con.execute(ONE_SIDED_QUERY).fetchone()
    split_rows = con.execute(SPLITS_QUERY).fetchall()
    con.close()

    print(f"input: {len(parquet_paths)} parquet file(s), {pitch_rows} pitch rows")
    print(f"window: {date_min} .. {date_max}")
    print(f"plate appearances (woba_denom > 0): {int(total_pa)}")
    print(f"league wOBA baseline: {league_woba:.4f}")
    if unmatched_pa:
        print(
            f"WARNING: {int(unmatched_pa)} PA from batters missing in {seed_path} "
            "(stand-profile fallback applied); regenerate the handedness seed "
            "from these parquets before trusting the map"
        )
    print(
        f"one-sided batters excluded from deltas: {int(one_sided_batters)} ({int(one_sided_pa)} PA)"
    )

    splits: dict[str, tuple[int, float, float]] = {
        grp: (int(n), float(hpa), float(s)) for grp, n, hpa, s in split_rows
    }

    print()
    print("delta-method platoon splits (within-batter, harmonic-mean weighted):")
    print(f"{'group':7} {'n_batters':>9} {'harmonic_pa':>12} {'split':>9}  reference")
    for grp in ("R", "L", "S"):
        if grp not in splits:
            print(f"{grp:7} {'-':>9} {'-':>12} {'-':>9}  no eligible batters in window")
            continue
        n, hpa, s = splits[grp]
        ref = BOOK_REFERENCE.get(grp)
        ref_txt = f"The Book +{ref:.3f}" if ref is not None else "near zero expected"
        print(f"{grp:7} {n:>9} {hpa:>12.1f} {s:>+9.4f}  {ref_txt}")

    rows = _map_rows(splits)
    print()
    print("calibrated map (league-neutral centering, ADR 0016 sign convention):")
    print(f"{'matchup':8} {'signal':>8}  source")
    for matchup, signal, source_group, _, _, _ in rows:
        print(f"{matchup:8} {signal:>+8.4f}  {source_group} split / 2")

    observed = {r[0] for r in rows}
    all_buckets = [
        "R_vs_R",
        "R_vs_L",
        "R_vs_S",
        "L_vs_R",
        "L_vs_L",
        "L_vs_S",
        "S_vs_R",
        "S_vs_L",
        "S_vs_S",
    ]
    missing = [b for b in all_buckets if b not in observed]
    if missing:
        print()
        print(f"unobserved map buckets (no data in this window): {', '.join(missing)}")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "matchup",
                "signal_value",
                "source_group",
                "group_split",
                "n_batters",
                "harmonic_pa",
                "league_woba",
            ]
        )
        for matchup, signal, source_group, group_split, n_batters, harmonic_pa in rows:
            w.writerow(
                [
                    matchup,
                    round(signal, 4),
                    source_group,
                    round(group_split, 4),
                    n_batters,
                    round(harmonic_pa, 1),
                    round(league_woba, 4),
                ]
            )
    print()
    print(f"wrote {out_path} ({len(rows)} buckets)")

    if module_out:
        write_runtime_module(rows, date_min, date_max, int(total_pa), module_out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parquet", nargs="+", required=True, help="Statcast parquet path(s) to calibrate from"
    )
    parser.add_argument("--handedness-seed", default=DEFAULT_SEED)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument(
        "--module-out",
        default=None,
        help="also write the runtime module (pass signals/matchup_calibration.py "
        "on the full-season run; omitted = seed CSV only)",
    )
    args = parser.parse_args()
    build(args.parquet, args.handedness_seed, args.out, args.module_out)


if __name__ == "__main__":
    main()
