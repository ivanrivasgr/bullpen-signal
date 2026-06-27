-- Natural-key uniqueness for mart_should_have_fired_ledger.
--
-- The ledger reads the streaming signal (ADR 0023), and the stream is not
-- the batch. A pitch that the real-time path saw more than once — a late
-- arrival re-sending it with a different event_time — is two facts about
-- what the system observed, not a duplicate to collapse. The batch path
-- consolidates re-sent pitches through its incremental unique_key merge;
-- the streaming path records each observation as it happened, which is the
-- divergence the reconciliation exists to show (ADR 0001).
--
-- So the identity of a streaming ledger row is the pitch AND the moment it
-- was emitted: (game_pk, at_bat_number, pitch_number, signal_event_time).
-- Uniqueness on the three-column batch key would be wrong here — it would
-- flag the stream's real multiplicity as an error. This test asserts the
-- real identity: no two rows share the same pitch at the same emission
-- instant. Two reduced rows for one pitch at different event_times are
-- valid and expected; two at the same event_time would be a genuine
-- double-emission bug.
SELECT
    game_pk,
    at_bat_number,
    pitch_number,
    signal_event_time,
    COUNT(*) AS occurrences
FROM {{ ref("mart_should_have_fired_ledger") }}
GROUP BY game_pk, at_bat_number, pitch_number, signal_event_time
HAVING COUNT(*) > 1
