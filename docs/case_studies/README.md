# Case studies

Each case study is a short, dated note tied to specific snapshots in the
lakehouse. The pattern is always the same: a situation, what streaming
said, what batch ultimately said, the delta, and why it mattered.

Case studies are the raw material for the Medium article and for LinkedIn
posts. Write them as you find them; do not save them for publication day.

## Template

Copy `_template.md` to `YYYY-MM-DD-short-slug.md`.

## Target mix

Aim for a balanced set:

- **Streaming was right, batch confirmed.** Shows the value of real-time.
- **Streaming was right, batch disagreed.** Honest — when the streaming
  signal beat the canonical data, because the canonical data was itself
  corrected later.
- **Streaming was wrong, batch corrected.** Shows the value of reconciliation.
- **Streaming was wrong, batch would have been too late.** The hardest,
  most interesting case: neither was sufficient.

A good article needs at least one of each.
