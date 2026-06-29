"""silver_fatigue_signal -- per-pitch in-game fatigue from mechanical deviation.

dbt Python model. For each pitcher in each game, this measures how far each
pitch deviates from that pitcher's own fresh in-game baseline, using the
Mahalanobis distance over three pitch-tracking features: release velocity,
release spin rate, and command (distance of the pitch location from the strike
zone center).

Method (ADR 0026, D2). This follows the framework Dillon et al. (2025,
Orthopaedic Journal of Sports Medicine; senior author is the New York Yankees'
head team physician) use for in-game mechanical-deviation monitoring: features
are standardized within pitcher using only the pitcher's control-period data,
and a Mahalanobis distance quantifies multivariate deviation from that baseline,
accounting for the correlation between features (a tired pitcher tends to lose
velocity and spin together, so they should not be double-counted). Higher
distance means greater departure from the pitcher's typical mechanics.

The paper uses five features (velocity, spin, extension, arm angle,
acceleration); this model uses the three available in the bronze Statcast
feed -- velocity, spin, and command -- and notes the others as a known gap.

Baseline: the pitcher's first N pitches in the game (fresh), per pitcher per
game. Each later pitch gets a Mahalanobis distance from that baseline's mean and
covariance. The dashboard also shows the per-feature components, so the
standardized per-feature z-scores (velocity, spin, command) are emitted
alongside the composite distance.

This is the streaming-as-of-emission and the canonical computation both: fatigue
depends on the pitch-tracking values carried on each event, so the two reads
diverge only where a correction changed those values (ADR 0001, D4).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Minimum pitches needed to estimate a stable 3x3 covariance for the baseline.
# Below this, a pitcher-game cannot get a reliable Mahalanobis baseline.
BASELINE_N = 15
# Strike zone center in Statcast coordinates: plate_x = 0 (middle), plate_z is
# the vertical midpoint of the zone, ~2.5 ft for a typical batter.
ZONE_CENTER_Z = 2.5


def _command_distance(plate_x: pd.Series, plate_z: pd.Series) -> pd.Series:
    """Command feature: Euclidean distance of the pitch location from the zone
    center. Larger = further from the intended target = looser command."""
    return np.sqrt(plate_x.astype(float) ** 2 + (plate_z.astype(float) - ZONE_CENTER_Z) ** 2)


def _mahalanobis_for_group(g: pd.DataFrame) -> pd.DataFrame:
    """Compute per-pitch Mahalanobis distance and per-feature z-scores against
    the pitcher's fresh baseline within this game."""
    g = g.sort_values("pitch_seq").copy()
    feats = ["velocity", "spin", "command"]

    # Baseline: the first BASELINE_N pitches of this pitcher in this game.
    baseline = g.iloc[:BASELINE_N]
    if len(baseline) < BASELINE_N:
        # Not enough fresh pitches to build a baseline. Emit nulls; the pitcher
        # did not throw enough in this game to measure fatigue against a stable
        # reference. Honest gap rather than a fabricated number.
        for c in [
            "fatigue",
            "fatigue_velocity_component",
            "fatigue_spin_component",
            "fatigue_command_component",
        ]:
            g[c] = np.nan
        return g

    x_base = baseline[feats].to_numpy(dtype=float)
    mu = x_base.mean(axis=0)
    cov = np.cov(x_base, rowvar=False)

    # Regularize the covariance so it is invertible even if a feature barely
    # moved in the baseline (e.g. very consistent spin). Small ridge on the
    # diagonal; standard practice for stable Mahalanobis on short windows.
    cov_reg = cov + np.eye(len(feats)) * 1e-6
    try:
        cov_inv = np.linalg.inv(cov_reg)
    except np.linalg.LinAlgError:
        for c in [
            "fatigue",
            "fatigue_velocity_component",
            "fatigue_spin_component",
            "fatigue_command_component",
        ]:
            g[c] = np.nan
        return g

    # Per-feature standard deviations from the baseline, for the per-feature
    # z-scores the dashboard displays.
    sd = x_base.std(axis=0, ddof=1)
    sd_safe = np.where(sd < 1e-9, 1e-9, sd)

    x_all = g[feats].to_numpy(dtype=float)
    diff = x_all - mu

    # Mahalanobis distance per pitch.
    md = np.sqrt(np.einsum("ij,jk,ik->i", diff, cov_inv, diff))

    # Per-feature z-scores. Velocity and spin are oriented so that a DROP
    # (fatigue) is positive: a tired pitcher loses velo/spin, so we negate the
    # raw z (which would be negative on a drop). Command is oriented so that a
    # larger location-distance (worse command) is positive.
    z = diff / sd_safe
    z_velo = -z[:, 0]
    z_spin = -z[:, 1]
    z_command = z[:, 2]

    g["fatigue"] = md
    g["fatigue_velocity_component"] = z_velo
    g["fatigue_spin_component"] = z_spin
    g["fatigue_command_component"] = z_command
    return g


def model(dbt, session):
    dbt.config(materialized="table")

    src = dbt.ref("silver_pitch_events")
    df = (
        src.df()
        if hasattr(src, "df")
        else session.table(str(src)).to_pandas()
        if hasattr(session, "table")
        else src
    )

    # Pull just what we need, drop rows missing the tracking features.
    cols = [
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "pitcher_id",
        "event_time",
        "release_speed",
        "release_spin_rate",
        "plate_x",
        "plate_z",
        "is_late_arrival",
        "is_duplicate",
    ]
    df = df[cols].copy()
    df = df.dropna(subset=["release_speed", "release_spin_rate", "plate_x", "plate_z"])

    df["velocity"] = df["release_speed"].astype(float)
    df["spin"] = df["release_spin_rate"].astype(float)
    df["command"] = _command_distance(df["plate_x"], df["plate_z"])

    # Within-game pitch order per pitcher (the sequence that defines "fresh").
    df["pitch_seq"] = (
        df.sort_values(["game_pk", "pitcher_id", "at_bat_number", "pitch_number"])
        .groupby(["game_pk", "pitcher_id"])
        .cumcount()
    )

    pieces = []
    for _, g in df.groupby(["game_pk", "pitcher_id"], sort=False):
        pieces.append(_mahalanobis_for_group(g))
    out = pd.concat(pieces, ignore_index=True)

    result = out[
        [
            "game_pk",
            "at_bat_number",
            "pitch_number",
            "pitcher_id",
            "event_time",
            "fatigue",
            "fatigue_velocity_component",
            "fatigue_spin_component",
            "fatigue_command_component",
            "is_late_arrival",
            "is_duplicate",
        ]
    ].reset_index(drop=True)

    return result
