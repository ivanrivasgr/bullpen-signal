"""Signal generation for Bullpen Signal.

Each module under this package produces one signal type. Modules are
pure functions over upstream events — no I/O, no state, no Kafka. The
replay engine and the future Flink job both call into these modules.

ADR 0016 governs the matchup signal design.
"""
