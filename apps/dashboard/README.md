# Dashboard

Streamlit app with three tabs:

- **Live dugout** — what the streaming path currently believes.
- **Canonical truth** — what batch recomputes after the fact.
- **Reconciliation** — delta between them per alert, per signal, per game.

Phase 0 renders placeholder values. Phase 1 wires Live to the Kafka
`alerts.v1` topic. Phase 2 wires Canonical to the gold marts. Phase 3 wires
Reconciliation to its dedicated schema.

## Design notes

The aesthetic is meant to match the "luxury front-office" direction already
established in BaseballIQ. Muted palette, dense information, no toy gauges.
Any visual that a GM would laugh at in a real dugout does not belong here.

## Run

```bash
streamlit run apps/dashboard/main.py
```
