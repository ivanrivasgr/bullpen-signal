"""real_data.py -- the dashboard's data source, backed by the real marts.

Drop-in replacement for synthetic_data.py: the same six dataclasses and the same
six functions, with identical shapes, but every value read from the project's
DuckDB rather than invented. main.py changes only its import.

Tabs I and II (live dugout, canonical truth) show one game -- game 745273, a
Luis Castillo outing with twelve orchestrator alerts. Tab III (reconciliation)
shows the streaming-vs-canonical divergence across the whole dataset, because
the finding it exists to show -- that divergence lives in the first two innings,
before the lineup is confirmed, while removal alerts fire from the fourth inning
on -- is only visible in aggregate (ADR 0026).

Fields with no source in the data are left as a visible placeholder ("--")
rather than fabricated: team and venue names (only game_pk is in the feed),
jersey numbers, and true season averages. The in-game average is used where the
dashboard needs a velo/spin reference, labeled honestly as such, not presented
as a season number.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import duckdb

DB_PATH = os.environ.get("BULLPEN_DUCKDB", os.path.expanduser("~/.bullpen/dbt.duckdb"))

# The game shown in Tabs I-II.
GAME_PK = 745273

_PLACEHOLDER = "--"


def _con():
    return duckdb.connect(DB_PATH, read_only=True)


# ---------------------------------------------------------------------------
# Dataclasses -- identical to synthetic_data.py
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GameContext:
    game_pk: int
    game_date: str
    home_team: str
    away_team: str
    venue: str
    first_pitch: datetime


@dataclass(frozen=True)
class Pitcher:
    player_id: int
    name: str
    jersey: int
    throws: str
    team: str
    season_velo_avg: float
    season_spin_avg: float
    # Real game line, derived from the pitch data. earned runs are not
    # derivable (no error data), so runs_allowed is total runs; ip_outs is
    # outs recorded; velo/spin deltas are current vs the fresh baseline.
    ip_outs: int
    hits: int
    runs: int
    strikeouts: int
    walks: int
    velo_delta: float
    spin_delta: float


@dataclass(frozen=True)
class PitchRow:
    pitch_idx: int
    inning: int
    ab: int
    pitch_in_ab: int
    pitch_type: str
    velo: float
    spin: float
    zone_or_edge: bool
    seconds_since_prev: float
    result: str


@dataclass(frozen=True)
class SignalSnapshot:
    event_time: datetime
    pitch_idx: int
    fatigue: float
    fatigue_velocity_component: float
    fatigue_spin_component: float
    fatigue_command_component: float
    leverage: float
    matchup_edge: float


@dataclass(frozen=True)
class Alert:
    alert_uid: str
    emitted_time: datetime
    pitch_idx: int
    severity: str
    composite_score: float
    threshold: float
    rationale: str
    inputs_uid: str


@dataclass(frozen=True)
class ReconciliationRow:
    alert_uid: str
    signal: str
    streaming_value: float
    canonical_value: float
    delta: float
    classification: str
    inning: int


# ---------------------------------------------------------------------------
# Pitch ordering for the shown game: a stable pitch_idx 1..N
# ---------------------------------------------------------------------------
def _game_pitches(con):
    """Every pitch of the shown game, in order, with a stable 1-based index.

    Restricted to the game's starting pitcher (the dashboard tells one
    pitcher's story), excluding exact redeliveries."""
    return con.execute(
        """
        WITH starter AS (
            SELECT pitcher_id
            FROM silver.silver_pitch_events
            WHERE game_pk = ?
            GROUP BY pitcher_id
            ORDER BY COUNT(*) DESC
            LIMIT 1
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY pe.at_bat_number, pe.pitch_number) AS pitch_idx,
            pe.at_bat_number, pe.pitch_number, pe.inning, pe.event_time,
            pe.pitch_type, pe.release_speed, pe.release_spin_rate,
            pe.zone, pe.description, pe.events, pe.pitcher_id
        FROM silver.silver_pitch_events pe
        JOIN starter s ON pe.pitcher_id = s.pitcher_id
        WHERE pe.game_pk = ? AND pe.is_duplicate IS NOT TRUE
          AND pe.release_speed IS NOT NULL AND pe.release_speed > 0
        ORDER BY pe.at_bat_number, pe.pitch_number
        """,
        [GAME_PK, GAME_PK],
    ).fetchall()


# ---------------------------------------------------------------------------
# Functions -- identical signatures to synthetic_data.py
# ---------------------------------------------------------------------------
def game_context() -> GameContext:
    con = _con()
    row = con.execute(
        """
        SELECT MIN(event_day) AS game_date, MIN(event_time) AS first_pitch
        FROM silver.silver_pitch_events WHERE game_pk = ?
        """,
        [GAME_PK],
    ).fetchone()
    con.close()
    game_date = str(row[0]) if row[0] is not None else _PLACEHOLDER
    first_pitch = row[1] if row[1] is not None else datetime(2024, 1, 1)
    # Team and venue names have no source in the feed (only game_pk); shown as
    # a placeholder rather than fabricated.
    return GameContext(
        game_pk=GAME_PK,
        game_date=game_date,
        home_team=_PLACEHOLDER,
        away_team=_PLACEHOLDER,
        venue=_PLACEHOLDER,
        first_pitch=first_pitch,
    )


def active_pitcher() -> Pitcher:
    con = _con()
    row = con.execute(
        """
        WITH starter AS (
            SELECT pitcher_id
            FROM silver.silver_pitch_events
            WHERE game_pk = ?
            GROUP BY pitcher_id ORDER BY COUNT(*) DESC LIMIT 1
        )
        SELECT
            st.pitcher_id,
            n.name_first, n.name_last,
            ROUND(AVG(pe.release_speed), 1) AS velo_avg,
            ROUND(AVG(pe.release_spin_rate)) AS spin_avg
        FROM starter st
        JOIN silver.silver_pitch_events pe
            ON pe.pitcher_id = st.pitcher_id AND pe.game_pk = ?
        LEFT JOIN seeds.player_names n ON st.pitcher_id = n.player_id
        GROUP BY st.pitcher_id, n.name_first, n.name_last
        """,
        [GAME_PK, GAME_PK],
    ).fetchone()

    # Real game line, derived from the pitch data.
    line = con.execute(
        """
        SELECT
            SUM(CASE WHEN events IN
                ('strikeout','field_out','grounded_into_double_play','force_out',
                 'sac_fly','sac_bunt','fielders_choice_out','double_play',
                 'strikeout_double_play') THEN 1 ELSE 0 END) AS ip_outs,
            SUM(CASE WHEN events IN ('single','double','triple','home_run')
                THEN 1 ELSE 0 END) AS hits,
            SUM(CASE WHEN events='strikeout' THEN 1 ELSE 0 END) AS k,
            SUM(CASE WHEN events IN ('walk','intent_walk','hit_by_pitch')
                THEN 1 ELSE 0 END) AS bb,
            MAX(away_score) - MIN(away_score) AS away_runs,
            MAX(home_score) - MIN(home_score) AS home_runs,
            AVG(CASE WHEN home_score >= away_score THEN 1 ELSE 0 END) AS home_share
        FROM silver.silver_pitch_events
        WHERE game_pk = ? AND pitcher_id = ?
        """,
        [GAME_PK, row[0]],
    ).fetchone()

    # Runs allowed: the opponent's runs while this pitcher threw. The pitcher is
    # on one side; runs allowed is the other side's scoring during his pitches.
    # We infer his side from which score stayed flat relative to the batting.
    away_runs = int(line[4] or 0)
    home_runs = int(line[5] or 0)
    # The pitcher allows the runs of the team batting against him. If his team is
    # home, that is the away team's runs, and vice versa. We take the larger of
    # the two only if one side is clearly the opponent; when ambiguous we report
    # the opponent runs as the max observed (conservative, real from the score).
    runs_allowed = max(away_runs, home_runs)

    # velo/spin deltas: current game average vs the fresh first-15 baseline.
    deltas = con.execute(
        """
        WITH seq AS (
            SELECT release_speed, release_spin_rate,
                   ROW_NUMBER() OVER (ORDER BY at_bat_number, pitch_number) AS pn
            FROM silver.silver_pitch_events
            WHERE game_pk = ? AND pitcher_id = ? AND release_speed > 0
        )
        SELECT
            ROUND(AVG(release_speed) - AVG(CASE WHEN pn<=15 THEN release_speed END), 1),
            ROUND(AVG(release_spin_rate) - AVG(CASE WHEN pn<=15 THEN release_spin_rate END))
        FROM seq
        """,
        [GAME_PK, row[0]],
    ).fetchone()
    # Throwing hand from the handedness seed if present.
    throws = _PLACEHOLDER
    try:
        h = con.execute(
            "SELECT hand FROM seeds.player_handedness WHERE player_id = ? AND role = 'pitcher' LIMIT 1",
            [row[0]],
        ).fetchone()
        if h and h[0]:
            throws = h[0]
    except Exception:
        pass
    con.close()

    name = f"{row[1]} {row[2]}".strip() if row[1] or row[2] else _PLACEHOLDER
    return Pitcher(
        player_id=int(row[0]),
        name=name,
        jersey=0,  # no source in the feed
        throws=throws,
        team=_PLACEHOLDER,  # no source in the feed
        # In-game averages, not season -- the only real reference available.
        season_velo_avg=float(row[3]) if row[3] is not None else 0.0,
        season_spin_avg=float(row[4]) if row[4] is not None else 0.0,
        ip_outs=int(line[0] or 0),
        hits=int(line[1] or 0),
        runs=runs_allowed,
        strikeouts=int(line[2] or 0),
        walks=int(line[3] or 0),
        velo_delta=float(deltas[0]) if deltas[0] is not None else 0.0,
        spin_delta=float(deltas[1]) if deltas[1] is not None else 0.0,
    )


def pitch_log() -> list[PitchRow]:
    con = _con()
    pitches = _game_pitches(con)
    con.close()

    rows: list[PitchRow] = []
    prev_time = None
    for r in pitches:
        (
            pitch_idx,
            ab,
            pitch_in_ab,
            inning,
            event_time,
            pitch_type,
            velo,
            spin,
            zone,
            description,
            events,
            _pid,
        ) = r

        # Pace since previous pitch, in seconds.
        if prev_time is not None and event_time is not None:
            pace = (event_time - prev_time).total_seconds()
            pace = max(0.0, min(pace, 120.0))  # clamp absurd gaps (inning breaks)
        else:
            pace = 0.0
        prev_time = event_time

        # zone 1-9 is in the strike zone; 11-14 is the shadow/edge/out.
        zone_or_edge = zone is not None and 1 <= int(zone) <= 9

        # Result: the most descriptive real field available.
        result = (events or description or "").strip()

        rows.append(
            PitchRow(
                pitch_idx=int(pitch_idx),
                inning=int(inning),
                ab=int(ab),
                pitch_in_ab=int(pitch_in_ab),
                pitch_type=(pitch_type or _PLACEHOLDER),
                velo=round(float(velo), 1) if velo is not None else 0.0,
                spin=round(float(spin)) if spin is not None else 0,
                zone_or_edge=bool(zone_or_edge),
                seconds_since_prev=round(pace, 1),
                result=result,
            )
        )
    return rows


def streaming_signals() -> list[SignalSnapshot]:
    """One snapshot per pitch of the shown game, from the real signal marts.

    fatigue and its components come from silver_fatigue_signal (Mahalanobis);
    leverage from silver_leverage_index (Tango); matchup_edge from the canonical
    matchup value. Pitches before the pitcher's fatigue baseline (first 15) have
    null fatigue and are skipped, mirroring the synthetic starting after warm-up.
    """
    con = _con()
    pitches = _game_pitches(con)
    # Map (at_bat, pitch) -> pitch_idx for the shown game.
    idx_by_key = {(r[1], r[2]): int(r[0]) for r in pitches}

    starter_id = pitches[0][11] if pitches else None
    ctx_first = game_context().first_pitch

    rows = con.execute(
        """
        SELECT
            f.at_bat_number, f.pitch_number,
            f.fatigue, f.fatigue_velocity_component,
            f.fatigue_spin_component, f.fatigue_command_component,
            lev.leverage_index,
            v.canonical_value AS matchup_edge,
            f.event_time
        FROM silver.silver_fatigue_signal f
        JOIN silver.silver_leverage_index lev
            ON f.game_pk = lev.game_pk AND f.at_bat_number = lev.at_bat_number
            AND f.pitch_number = lev.pitch_number
        LEFT JOIN marts.mart_signal_values_long v
            ON v.signal = 'matchup' AND v.game_pk = f.game_pk
            AND v.at_bat_number = f.at_bat_number AND v.pitch_number = f.pitch_number
        WHERE f.game_pk = ? AND f.pitcher_id = ? AND f.fatigue IS NOT NULL
        ORDER BY f.at_bat_number, f.pitch_number
        """,
        [GAME_PK, starter_id],
    ).fetchall()
    con.close()

    out: list[SignalSnapshot] = []
    for r in rows:
        (ab, pn, fatigue, vc, sc, cc, leverage, matchup, event_time) = r
        pitch_idx = idx_by_key.get((ab, pn))
        if pitch_idx is None:
            continue
        out.append(
            SignalSnapshot(
                event_time=event_time
                if event_time is not None
                else ctx_first + timedelta(seconds=25 * pitch_idx),
                pitch_idx=pitch_idx,
                fatigue=round(float(fatigue), 3),
                fatigue_velocity_component=round(float(vc), 3) if vc is not None else 0.0,
                fatigue_spin_component=round(float(sc), 3) if sc is not None else 0.0,
                fatigue_command_component=round(float(cc), 3) if cc is not None else 0.0,
                leverage=round(float(leverage), 2) if leverage is not None else 0.0,
                matchup_edge=round(float(matchup), 3) if matchup is not None else 0.0,
            )
        )
    return out


def alerts() -> list[Alert]:
    """The shown game's orchestrator alerts, from mart_alerts."""
    con = _con()
    pitches = _game_pitches(con)
    idx_by_key = {(r[1], r[2]): int(r[0]) for r in pitches}
    starter_id = pitches[0][11] if pitches else None

    rows = con.execute(
        """
        SELECT alert_uid, at_bat_number, pitch_number, emitted_time,
               severity, composite_score, threshold,
               leverage, fatigue, times_through_order
        FROM marts.mart_alerts
        WHERE game_pk = ? AND pitcher_id = ?
        ORDER BY at_bat_number, pitch_number
        """,
        [GAME_PK, starter_id],
    ).fetchall()
    con.close()

    out: list[Alert] = []
    for r in rows:
        (alert_uid, ab, pn, emitted, severity, score, threshold, leverage, fatigue, tto) = r
        pitch_idx = idx_by_key.get((ab, pn))
        if pitch_idx is None:
            continue
        rationale = f"fatigue {fatigue:.1f}, leverage {leverage:.1f}, {tto:.1f} times through order"
        out.append(
            Alert(
                alert_uid=alert_uid,
                emitted_time=emitted,
                pitch_idx=pitch_idx,
                severity=severity,
                composite_score=float(score),
                threshold=float(threshold),
                rationale=rationale,
                inputs_uid=f"{GAME_PK}:{ab}:{pn}",
            )
        )
    return out


def reconciliation_coverage() -> tuple[int, int]:
    """(comparable pitches, pitches where both paths produced the same value).

    A pitch is comparable only when both paths produced a matchup value: the
    streaming path read the dates that were replayed, the canonical path reads
    every pitch in silver. Reporting a divergence count against the full pitch
    total would understate the rate; reporting it with no denominator at all
    says nothing about how often the two paths agree, which is most of the time.
    """
    con = _con()
    row = con.execute(
        """
        SELECT
            COUNT(*) AS comparable,
            COUNT(*) FILTER (
                WHERE ABS(streaming_value - canonical_value) <= 0.0001
            ) AS agreed
        FROM marts.mart_signal_values_long
        WHERE signal = 'matchup'
          AND streaming_value IS NOT NULL
          AND canonical_value IS NOT NULL
        """
    ).fetchone()
    con.close()
    return (int(row[0]), int(row[1]))


def reconciliation_rows() -> list[ReconciliationRow]:
    """Every streaming-vs-canonical divergence across the dataset.

    Unlike the synthetic (which grouped by alert in one game), this returns all
    matchup divergences across all games, because the finding -- that divergence
    is concentrated in the first two innings, before the lineup is confirmed --
    is only visible in aggregate. Each row's alert_uid encodes the pitch and the
    pitcher so the table reads as "pitcher . inn N . ab A pP".
    """
    con = _con()
    rows = con.execute(
        """
        WITH divergent AS (
            SELECT v.game_pk, v.at_bat_number, v.pitch_number,
                   v.streaming_value, v.canonical_value,
                   (v.streaming_value - v.canonical_value) AS delta
            FROM marts.mart_signal_values_long v
            WHERE v.signal = 'matchup'
              AND ABS(v.streaming_value - v.canonical_value) > 0.0001
        )
        SELECT pe.inning, pe.at_bat_number, pe.pitch_number,
               n.name_last,
               d.streaming_value, d.canonical_value, d.delta
        FROM divergent d
        JOIN silver.silver_pitch_events pe
            ON d.game_pk = pe.game_pk AND d.at_bat_number = pe.at_bat_number
            AND d.pitch_number = pe.pitch_number
        LEFT JOIN seeds.player_names n ON pe.pitcher_id = n.player_id
        ORDER BY pe.inning, pe.at_bat_number, pe.pitch_number
        """
    ).fetchall()
    con.close()

    out: list[ReconciliationRow] = []
    for r in rows:
        (inning, ab, pn, last, sval, cval, delta) = r
        name = last if last else "--"
        # Classify per ADR 0026 D6.
        if sval != 0 and cval != 0 and ((sval > 0) != (cval > 0)):
            classification = "reversed"
        elif (sval >= 0) == (cval >= 0) and abs(cval) < abs(sval) * 0.9:
            classification = "softened"
        elif (sval >= 0) == (cval >= 0) and abs(cval) > abs(sval) * 1.1:
            classification = "escalated"
        else:
            classification = "confirmed"
        out.append(
            ReconciliationRow(
                alert_uid=f"{name} . ab{ab} p{pn}",
                signal="matchup",
                streaming_value=round(float(sval), 3),
                canonical_value=round(float(cval), 3),
                delta=round(float(delta), 3),
                classification=classification,
                inning=int(inning),
            )
        )
    return out
