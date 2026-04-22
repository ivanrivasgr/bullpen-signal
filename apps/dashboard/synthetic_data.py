"""Synthetic narrative data for the Phase 0 dashboard.

This is not random data. It is a carefully constructed scenario that tells
one complete story: a starter losing his stuff in a high-leverage spot,
streaming alerting early, and batch later confirming the call. Every
number in the dashboard traces back to this single data source.

When Phase 1 wires Kafka in, this module is replaced by a live feed.
The shape of what it returns does not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


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


def game_context() -> GameContext:
    return GameContext(
        game_pk=745642,
        game_date="2024-06-15",
        home_team="Rangers",
        away_team="Tigers",
        venue="Globe Life Field",
        first_pitch=datetime(2024, 6, 15, 19, 5, tzinfo=UTC),
    )


def active_pitcher() -> Pitcher:
    return Pitcher(
        player_id=676130,
        name="Martinez, J.",
        jersey=32,
        throws="R",
        team="Rangers",
        season_velo_avg=94.3,
        season_spin_avg=2312.0,
    )


def pitch_log() -> list[PitchRow]:
    """98 pitches telling one story.

    First 20: crisp. Velocity ~94.5, spin at baseline, command in zone.
    Pitches 21-60: still solid, gradual creep on pace.
    Pitches 61-85: the slide. Velocity drops 2-3 mph, spin -150 RPM, zone% falls.
    Pitches 86-98: falling off a cliff. 91 mph heaters, walk and hard contact.
    """
    rows: list[PitchRow] = []
    types = ["FF", "SL", "CH", "CU"]
    for i in range(1, 99):
        if i <= 20:
            velo = 94.6 - (i % 3) * 0.15
            spin = 2310 + (i % 4) * 8
            zone = i % 7 != 0
            pace = 18 + (i % 4)
        elif i <= 60:
            velo = 94.1 - (i - 20) * 0.01 - (i % 3) * 0.2
            spin = 2300 - (i - 20) * 0.5
            zone = i % 5 != 0
            pace = 21 + (i % 5)
        elif i <= 85:
            velo = 93.0 - (i - 60) * 0.04 - (i % 3) * 0.3
            spin = 2270 - (i - 60) * 3.5
            zone = i % 3 != 0
            pace = 26 + (i % 6)
        else:
            velo = 91.8 - (i - 85) * 0.08
            spin = 2130 - (i - 85) * 4
            zone = i % 2 == 0
            pace = 30 + (i % 5)

        inning = min(1 + (i - 1) // 15, 7)
        ab = 1 + (i - 1) // 4
        pitch_in_ab = ((i - 1) % 4) + 1

        rows.append(
            PitchRow(
                pitch_idx=i,
                inning=inning,
                ab=ab,
                pitch_in_ab=pitch_in_ab,
                pitch_type=types[i % 4],
                velo=round(velo, 1),
                spin=round(spin),
                zone_or_edge=zone,
                seconds_since_prev=round(pace, 1),
                result="",
            )
        )
    return rows


def streaming_signals() -> list[SignalSnapshot]:
    """One signal snapshot per pitch from pitch 20 onward (warm-up done)."""
    pitches = pitch_log()
    ctx = game_context()
    out: list[SignalSnapshot] = []
    baseline_velo = sum(p.velo for p in pitches[:20]) / 20
    baseline_spin = sum(p.spin for p in pitches[:20]) / 20

    for p in pitches[19:]:
        prev = pitches[max(0, p.pitch_idx - 16) : p.pitch_idx]
        last15_velo = sum(q.velo for q in prev) / max(len(prev), 1)
        last15_spin = sum(q.spin for q in prev) / max(len(prev), 1)
        last15_zone = sum(1 for q in prev if q.zone_or_edge) / max(len(prev), 1)

        velo_delta = last15_velo - baseline_velo
        spin_delta = last15_spin - baseline_spin

        velo_component = max(0.0, min(1.0, -velo_delta / 3.5))
        spin_component = max(0.0, min(1.0, -spin_delta / 200))
        command_component = max(0.0, min(1.0, (0.68 - last15_zone) / 0.3))

        pitch_count_component = min(1.0, p.pitch_idx / 110)

        fatigue = (
            0.30 * velo_component
            + 0.20 * spin_component
            + 0.20 * command_component
            + 0.30 * pitch_count_component
        )

        # Leverage: baseline 1.0, grows through the game. Spikes late with tight score.
        if p.pitch_idx < 50:
            leverage = 0.8 + (p.pitch_idx / 200)
        elif p.pitch_idx < 80:
            leverage = 1.1 + (p.pitch_idx - 50) * 0.02
        else:
            leverage = 1.7 + (p.pitch_idx - 80) * 0.08

        # Matchup edge (expected wOBA allowed vs league baseline). Negative is good for pitcher.
        matchup = -0.020 + (fatigue - 0.4) * 0.08

        out.append(
            SignalSnapshot(
                event_time=ctx.first_pitch + timedelta(seconds=25 * p.pitch_idx),
                pitch_idx=p.pitch_idx,
                fatigue=round(fatigue, 3),
                fatigue_velocity_component=round(velo_component, 3),
                fatigue_spin_component=round(spin_component, 3),
                fatigue_command_component=round(command_component, 3),
                leverage=round(leverage, 2),
                matchup_edge=round(matchup, 3),
            )
        )
    return out


def alerts() -> list[Alert]:
    """Three alerts across the game: info, warning, action."""
    ctx = game_context()
    return [
        Alert(
            alert_uid="a1-info-leverage",
            emitted_time=ctx.first_pitch + timedelta(seconds=25 * 58),
            pitch_idx=58,
            severity="info",
            composite_score=0.41,
            threshold=0.40,
            rationale="Leverage rising past 1.5 with runner on. Starter still efficient.",
            inputs_uid="snap:745642:58",
        ),
        Alert(
            alert_uid="a2-warning-fatigue",
            emitted_time=ctx.first_pitch + timedelta(seconds=25 * 78),
            pitch_idx=78,
            severity="warning",
            composite_score=0.62,
            threshold=0.55,
            rationale="Velocity -2.1 mph over last 15. Spin -140 RPM vs baseline. Warm a reliever.",
            inputs_uid="snap:745642:78",
        ),
        Alert(
            alert_uid="a3-action-composite",
            emitted_time=ctx.first_pitch + timedelta(seconds=25 * 92),
            pitch_idx=92,
            severity="action",
            composite_score=0.81,
            threshold=0.70,
            rationale="Fatigue past threshold, leverage 2.4, unfavorable matchup vs next batter. Replace now.",
            inputs_uid="snap:745642:92",
        ),
    ]


def reconciliation_rows() -> list[ReconciliationRow]:
    return [
        ReconciliationRow("a1-info-leverage", "leverage", 1.52, 1.55, 0.03, "confirmed"),
        ReconciliationRow("a1-info-leverage", "fatigue", 0.38, 0.42, 0.04, "confirmed"),
        ReconciliationRow("a2-warning-fatigue", "fatigue", 0.62, 0.59, -0.03, "confirmed"),
        ReconciliationRow("a2-warning-fatigue", "matchup", -0.018, -0.025, -0.007, "softened"),
        ReconciliationRow("a2-warning-fatigue", "leverage", 1.94, 2.01, 0.07, "confirmed"),
        ReconciliationRow("a3-action-composite", "fatigue", 0.79, 0.82, 0.03, "confirmed"),
        ReconciliationRow("a3-action-composite", "leverage", 2.41, 2.38, -0.03, "confirmed"),
        ReconciliationRow("a3-action-composite", "matchup", -0.031, -0.028, 0.003, "confirmed"),
    ]
