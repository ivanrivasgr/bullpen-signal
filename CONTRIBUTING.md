# Contributing

This is a personal project, but the layout assumes public collaboration from
day one. If you are reading this after cloning the repo, welcome.

## Ground rules

- **One change, one reason.** A PR that reshapes the streaming path and the
  batch path at once is two PRs.
- **ADR before big moves.** New dependency, new service, new contract: open
  an ADR in `docs/adr/` first.
- **Tests are not negotiable.** Any model or job without a test fails
  review.
- **Case studies are part of the work, not extra.** If a change touches
  behavior that would affect a reconciliation delta, the PR adds or updates
  a case study.

## Local dev

```bash
make bootstrap   # one-time
make up          # local stack
make test        # unit
```

Integration tests require the local stack up. They are opt-in:
`pytest -m integration`.

## Commit style

Short imperative subject. Body explains *why* more than *what* — the diff
already shows what. Reference the ADR or spec in the body when relevant.
