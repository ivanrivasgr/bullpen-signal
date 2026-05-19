# Chad Corwin response to stationarity writeup

**Date received:** 2026-05-19
**Re:** `docs/mini_probe/2026_05_22_chad_stationarity_writeup.md`
**Commitment:** `EXT-2026-04-29-001`

## Response (verbatim)

Ivan,

You delivered on the commitment — and ahead of schedule. The writeup is exactly what I needed before the governance review: clean method, reproducible outputs, and honest caveats. The two-windows-is-a-sanity-check framing is the right one. You didn't oversell it.

The finding I'd flag as most load-bearing: the 62.5% directional skew toward lower-fatigue buckets in September. You noted the likely mechanism — injury and workload management quietly removing high-usage arms from the late-season cohort — but correctly deferred proving it. That deferral matters for the governance conversation, because if the skew is a population shift rather than threshold mis-calibration, adaptive thresholds would be solving the wrong problem. You'd be moving the fence to chase the players rather than holding the fence and tracking who left the field.

That distinction maps directly onto the stationarity question I raised in our earlier exchange. My retrospective sample has grown since then but is still thin enough that I can't call it a distribution. What your probe gives me is something I didn't have: directional evidence that drift, where it exists, is more likely to be cohort composition than threshold mis-fit. That's useful framing going into the review.

On your open question — adaptive vs static — I'm going to hold the static threshold through the review rather than adjust ahead of scored results. The 'should have fired' ledger you're building into Phase 3 is the right instrument for this. A correction rate on confirmed suppressions is more informative than a threshold re-fit on population-level activation rates. If the drift is cohort-driven the way your September numbers suggest, moving the threshold would obscure that signal rather than fix it.

Looking forward to seeing what Milestone 4 produces when live streaming meets canonical batch on these same games. The per-pitcher instability you found here — 19% modal shift, 14% shifting more than 20pp — is going to show up in the reconciliation layer as noise with a direction. You now know which direction to expect.

Chad

## Key takeaways for project direction

- **Governance decision:** Chad will hold the static threshold through his review rather than adjust ahead of scored results. The probe achieved its operational purpose.
- **Mechanism framing accepted:** the 62.5% directional skew toward lower-fatigue buckets in September is being treated as plausible evidence of cohort composition shift, not threshold mis-calibration.
- **Phase 3 anchor:** the "should have fired" ledger / correction rate on confirmed suppressions is named as the right instrument — not threshold re-fitting on population-level activation rates.
- **Phase 2 design constraint:** the per-pitcher instability found here (19% modal shift, 14% shifting >20pp) is expected to surface in the reconciliation layer as directional noise. Phase 2 must emit enough state for Phase 3 to detect that direction.
