# Schemas

Avro is the wire format for every topic. JSON is used only in Phase 0 smoke tests.

## Topics and schemas

| Topic | Schema | Notes |
|---|---|---|
| `pitches.raw` | `pitch_event.avsc` | One record per pitch, includes noise flags. |
| `game_state.raw` | `game_state_event.avsc` | Emitted on inning change, pitching change, pinch-hit, scoring play. |
| `corrections.cdc` | `correction_event.avsc` | Late-breaking field corrections, CDC-shaped. |
| `alerts.v1` | `alert_event.avsc` | Output of the streaming alert orchestrator. |

## Evolution rules

- Backward compatibility required. Never remove a field; mark it deprecated in the `doc`.
- New fields must have a default. Prefer `["null", T]` with `default: null`.
- Enum expansion is breaking for old consumers. Version the enum name instead (e.g. `SignalTypeV2`).

## Registering schemas

The local stack runs Redpanda's built-in schema registry on `http://localhost:18081`.
Registration is scripted in Phase 1; for now, these files are the source of truth.
