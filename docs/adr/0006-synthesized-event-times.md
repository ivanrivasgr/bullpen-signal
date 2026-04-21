# ADR 0006 — Synthesized event times in the replay engine

- **Status:** Accepted, with a caveat documented at the source
- **Date:** Phase 0

## Context

Statcast rows do not carry per-pitch wall-clock timestamps. MLB StatsAPI
has timestamps but at a coarser event granularity (plays, not pitches). The
streaming jobs need `event_time` to exist at pitch granularity for
watermarks and windowing to be meaningful.

## Decision

The replay engine synthesizes a monotonic `event_time` per game using a
realistic pitch cadence: ~23 seconds between pitches within an at-bat,
~90 seconds between at-bats. The synthesized series is stable given the
same input, so replay runs are reproducible across machines.

## Alternatives considered

- **Use `game_date` only.** All pitches at the same timestamp defeats
  watermarks.
- **Use StatsAPI play-level timestamps.** Correct in coarser units but
  does not resolve pitches within a plate appearance.
- **Use a synthetic uniform cadence (e.g. 15s).** Too clean — removes the
  at-bat gap that exercises late-arrival handling.

## Consequences

- The project's latency numbers are **relative**, not absolute. p95
  latencies are meaningful within a given replay configuration; they are
  not claims about real MLB feed latency.
- Anyone forking the repo for a different domain swaps this module; the
  replay engine's public interface does not change.
- This ADR is what turns a subtle trap into a documented trade-off. The
  caveat is also repeated in `ingestion/replay_engine/README.md` and in
  the Medium article's methodology section.
