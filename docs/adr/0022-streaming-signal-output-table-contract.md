# ADR 0022 - Streaming Matchup Signal Output Table Contract

- **Status:** Accepted
- **Date:** 2026-06-21

## Context

ADR 0021 set the order of the streaming migration: build streaming signal
generation first, feed the reconciliation last. The signal logic is now built
and proven in the Flink runtime — the handedness UDF, the emission UDTF, and the
shared core all three paths call. What remains is the job itself: read
pitches.raw, derive the matchup, expand into signal rows, and write them to a
table the reconciliation can read.

That output table needs a defined schema. ADR 0021 required "the same natural
key, the same vocabulary, the same signal definition" as the batch path, but did
not enumerate the columns. The batch table silver_matchup_signals materializes
25 columns, most of them inherited from silver_matchup_events (fatigue bucket,
both sides' handedness, audit columns) rather than produced by the signal itself.
Replicating all 25 in streaming would force the job to carry fields it does not
compute and the reconciliation does not read. Defining the streaming table by
what the batch happens to carry, rather than by what downstream consumes, would
bake inherited inertia into a new contract.

This ADR fixes the streaming output table's columns by deriving them from what
the reconciliation layer actually reads.

## Decision

The streaming matchup signal table carries exactly the columns that the two
downstream consumers read from the batch signal table, and no more.

mart_should_have_fired_ledger reads: game_pk, at_bat_number, pitch_number,
pitcher_id, batter_id, signal_value, confidence_band, lineup_state_at_emission,
event_time.

The revision producer reads: game_pk, at_bat_number, pitch_number, event_time,
handedness_matchup, signal_value, confidence_band, lineup_state_at_emission.

Their union is the contract:

- **Natural key:** game_pk, at_bat_number, pitch_number, plus
  lineup_state_at_emission. The fourth field is part of the key because an
  uncertain pitch emits two rows — reduced and full — that share the first three
  and are distinguished only by the emission state (ADR 0020). This matches the
  custom uniqueness test on the batch table.
- **Identity:** pitcher_id, batter_id, event_time.
- **Signal:** handedness_matchup, signal_value, confidence_band.

Types follow the batch table: the three IDs and game_pk are 64-bit integers,
at_bat_number and pitch_number are 32-bit, event_time is a timestamp with zone,
signal_value is double, and the string fields (handedness_matchup,
confidence_band, lineup_state_at_emission) are strings. handedness_matchup is
nullable, matching the batch, where a player absent from the handedness seed
yields a null matchup.

## What this deliberately excludes

The inherited columns — pitcher_fatigue_bucket, both sides' handedness, the
projected fields, the audit columns (is_late_arrival, is_duplicate,
correction_of), computed_at — are not in the streaming contract. They are not
read by the reconciliation or the revision producer, and the streaming job does
not compute them. If a future consumer needs one, it is added then, to both
paths, under its own change — not carried now on the chance it is wanted.

handedness_matchup is kept even though it is a derived field, because the
revision producer reads it and the reconciliation summary groups correction
rates by it. It is part of the contract, not inherited inertia.

## Consequences

The streaming table is lean and its every column is justified by a reader. The
apples-to-apples comparison ADR 0001 requires holds on these columns: the
reconciliation compares the streaming and batch signal for the same natural key
on signal_value and confidence_band, and both paths produce those identically
because they share the core that computes them.

The batch table keeps its 25 columns; this ADR does not change it. The two
tables therefore differ in width, which is intentional — the batch table is a
rich silver model with everything the events carried, while the streaming table
is exactly the signal contract. The reconciliation joins on the natural key and
reads only the contract columns, so the width difference does not affect it.
