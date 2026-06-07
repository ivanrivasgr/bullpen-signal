-- Natural key uniqueness for mart_reconciliation_summary.
-- One row per (lineup_state_at_emission, confidence_band, handedness_matchup).
SELECT
    lineup_state_at_emission,
    confidence_band,
    handedness_matchup,
    COUNT(*) AS occurrences
FROM {{ ref("mart_reconciliation_summary") }}
GROUP BY lineup_state_at_emission, confidence_band, handedness_matchup
HAVING COUNT(*) > 1
