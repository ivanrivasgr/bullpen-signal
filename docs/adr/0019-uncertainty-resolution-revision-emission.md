# ADR 0019 - Emitting Revisions When the Uncertainty Window Resolves

- **Status:** Superseded by ADR 0020
- **Date:** 2026-06-09
- **Note:** The intent of this ADR — closing the revision loop so the
  reconciliation layer records what the system would have corrected once
  the lineup confirmed — stands. Its mechanism does not. This ADR proposed
  the replay emit the resolution as a second signal; implementation showed
  signals are generated in dbt, not the replay, and that the first approach
  destroyed the observed batter. ADR 0020 records the corrected mechanism
  (preserve the observed batter, emit twice in dbt). Read 0020 alongside
  this document.

## Context

ADR 0014 introduced the BATTER_UNCERTAIN window: the first K seconds of a simulated late-lineup game, during which pitches are tagged `lineup_state = uncertain` and their batter is replaced with a projected batter (ADR 0015). ADR 0016 maps `lineup_state` to a `confidence_band`, so uncertain pitches emit a matchup signal with `confidence_band = reduced`. ADR 0017 defined the revision taxonomy, and the batch revision producer (commit fd4f6a5) turns consecutive signal emissions per pitch into revision events.

Commit bc906e7 activated the uncertainty window end-to-end. The should-have-fired ledger populated with 59 reduced-confidence signals, and the reconciliation summary produced real correction rates. But the revision producer emitted zero revisions, because the producer needs two emissions per natural key to compare, and the replay emits each pitch exactly once.

The gap is structural, not a bug. When a pitch falls inside the uncertainty window, the replay emits it once with the projected batter and `lineup_state = uncertain`. When the lineup later confirms, nothing re-evaluates that pitch. The system never records whether the projection was right, so there is no revision to compute and the baseline_confirmed / material_update distinction from ADR 0017 never gets exercised.

This is the load-bearing piece Chad named on 2026-05-19: the reconciliation layer is only meaningful if the system records what it would have corrected once the truth arrived. Without resolution emissions, the ledger captures the held-back decisions but never the moment they were validated or overturned.

## The mechanism that makes this tractable

The replay loop already has both pieces of information at the moment it processes an uncertain pitch. `row_to_pitch_event` reads the real batter from `row["batter"]` (the Statcast ground truth). `apply_uncertainty_window` then replaces it with the projected batter for the emitted event, but the original Statcast row — and therefore the real batter — is still in scope in the replay loop.

This means the replay does not need a separate confirmation process or a re-read of the topic. At the moment it emits an uncertain pitch, it knows the projection it published and the real batter that will be confirmed once the window closes. The revision is computable in the same loop.

## Decision

When the replay processes a pitch inside the uncertainty window, it emits the uncertain signal as today, and additionally records a deferred resolution. When the uncertainty window for that game closes (the first pitch whose event_time crosses window_end), the replay emits one resolution event per pitch that was uncertain in that game, comparing the projected batter against the real batter.

The resolution is not a re-emission of the pitch. It is a second matchup signal emission for the same natural key, carrying the real batter and `lineup_state = confirmed` (hence `confidence_band = full`). The existing revision producer then sees two emissions per uncertain pitch — the reduced one and the full one — and applies detect_revision:

- If the projected batter equals the real batter, the recomputed signal_value is identical and the revision is `baseline_confirmed` (the projection was right; confidence rose from reduced to full).
- If the projected batter differs from the real batter, the recomputed signal_value differs and the revision is `material_update` (the projection was wrong; the signal changed once truth arrived).

This is chosen over the two alternatives below because it is the only option that exercises the same data path the production streaming job will use, and it requires no new infrastructure.

### Why the replay, not a separate process or a dbt model

This is alternative 1 of the three considered during the 2026-06-08 design discussion. The other two are recorded here with the reasons they were not chosen.

**Alternative 2 — a separate confirmation process.** A standalone consumer reads uncertain signals from the topic and emits the confirmed counterpart once the real lineup is known. Rejected: the replay already knows the real batter at emission time (see the mechanism section), so a separate process would re-derive information the replay holds, adding a second point of failure and a second place where the projection-versus-real comparison logic lives. The streaming Flink job scheduled for 2026-06-20 will be that consumer in production, but in the batch replay world the replay is the natural home.

**Alternative 3 — a dbt model that synthesizes the second emission.** A silver model reads uncertain signals, joins the real batter from the canonical events, and writes a synthetic confirmed row. Rejected: this reconstructs in batch what the streaming path does in flight, which means it would be thrown away when the Flink streaming job lands on 2026-06-20. It also produces revision rows that never passed through Kafka, breaking the property that every revision in the lakehouse was published as an event. The dbt marts should read revisions that the producer emitted, not manufacture them.

## Design constraints on the implementation

These constraints bound the implementation that lands in the next commit. They are part of the decision, not implementation detail.

- The resolution emission must carry the same natural key (game_pk, at_bat_number, pitch_number) as the original uncertain pitch, so the revision producer groups them correctly. The natural key identifies the pitch, not the emission, so this is consistent with the existing model.

- The resolution must be emitted in event-time order relative to the original. The producer orders signals by (natural key, event_time); the resolution must have an event_time strictly greater than the uncertain emission so it sorts second. The window_end time is a natural choice — it is when confirmation arrives.

- The resolution emission must only happen for pitches that were actually uncertain. Pitches that were confirmed from the start (outside the window, or in games where the window was zero) get no resolution, because they were never in doubt.

- The replay must not emit a resolution if the lineup cache was absent. Without the cache there is no projection, every pitch is confirmed, and there is nothing to resolve. This preserves the existing cache-missing behavior from ADR 0014.

- Determinism must hold. Two replay runs with the same seed and cache must produce byte-identical resolution emissions, matching the determinism guarantee the uncertainty window already provides.

## Out Of Scope For This ADR

- The exact event_time assigned to the resolution emission beyond "at or after window_end". The implementation may choose window_end itself or the event_time of the first confirmed pitch; that is implementation detail as long as it sorts after the uncertain emission.
- Whether the resolution emission also flows through the Flink smoke job to Iceberg, or only to the matchup signals path. The current batch reconciliation reads silver_matchup_signals; the resolution must reach that table. How it reaches it (through the same Flink path or a direct materialization) is implementation detail.
- The Phase 3 streaming job that will replace the batch replay's resolution logic on 2026-06-20. This ADR governs the batch replay behavior until then; the streaming job will be its own ADR.
- Backfilling resolutions for replays that already ran without this behavior. The reconciliation marts are rebuilt per replay, so a fresh replay with the new behavior supersedes old data; no backfill is needed.

## Consequences

- The replay engine gains resolution-emission logic. The uncertain-pitch path records the projected and real batters; the window-close path emits the resolution signals. This is new behavior in a sensitive component, so it ships with explicit unit tests covering: a game with no uncertain pitches emits no resolutions, a game with uncertain pitches emits one resolution per uncertain pitch, the resolution carries the real batter, and determinism across two runs with the same seed.

- The revision producer (commit fd4f6a5) needs no change. It already groups by natural key and applies detect_revision over consecutive emissions. Once the replay emits two signals per uncertain pitch, the producer emits revisions without modification. This validates the producer's design: it was built against the contract, not against today's single-emission data.

- silver_matchup_signals gains a second row per uncertain pitch. The natural key uniqueness test on that table must account for this — the unique key becomes (game_pk, at_bat_number, pitch_number, lineup_state_at_emission) or (natural key, event_time), since a pitch now legitimately has both a reduced and a full emission. The implementation commit resolves which.

- The reconciliation summary's correction_rate becomes interpretable as designed: baseline_confirmed revisions are projections that held, material_update revisions are projections that were overturned. The ratio of the two, by handedness matchup, is the calibration signal Phase 3 feeds back into the placeholder magnitudes from ADR 0016.

## References

- ADR 0013: BATTER_UNCERTAIN state representation — `docs/adr/0013-batter-uncertain-state-representation.md`
- ADR 0014: Uncertainty window injection mechanism — `docs/adr/0014-uncertainty-window-injection-mechanism.md`
- ADR 0015: Projected batter source during uncertainty — `docs/adr/0015-projected-batter-source-during-uncertainty.md`
- ADR 0016: Matchup signal design — `docs/adr/0016-matchup-signal-design.md`
- ADR 0017: Revision taxonomy — `docs/adr/0017-revision-taxonomy.md`
- Batch revision producer — commit `fd4f6a5`
- Uncertainty window activation end-to-end — commit `bc906e7`
- Counterparty response naming the reconciliation layer as load-bearing — `docs/mini_probe/2026_05_19_chad_response.md`
