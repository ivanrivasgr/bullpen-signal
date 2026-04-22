# Marts

Gold-layer models. The canonical truth against which streaming is reconciled.

## Planned models (Phase 2)

| Model | Grain | Purpose |
|---|---|---|
| `fct_pitches_canonical` | One row per pitch | Deduplicated, corrections applied, enriched with pitcher and batter context. |
| `fct_fatigue_canonical` | Pitcher-game-pitch | Final fatigue score using the full batch feature set. |
| `fct_leverage_canonical` | Pitcher-game-state | Final leverage index, applying post-hoc substitution info. |
| `fct_matchup_canonical` | Pitcher-batter | Final matchup edge using season splits and park factors. |
| `dim_pitcher_season` | Pitcher-season | Season baselines: pitch mix, velocity, spin rate, usage. |
| `dim_batter_season` | Batter-season | Season splits by handedness and pitch type. |

## Grain rules

One row per documented key. Any duplicate is a bug; tests enforce this.

## Freshness expectations

Incremental runs every 15 minutes during a game day. A full refresh lands
overnight. The reconciliation mart depends on `fct_*_canonical` being
current, so their schedule defines the project's batch latency SLA.
