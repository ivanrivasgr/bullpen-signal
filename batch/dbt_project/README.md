# dbt project

Canonical-truth models over the Iceberg lakehouse. DuckDB in Phase 0 and 2
for iteration speed; a real Iceberg target joins in Phase 2.

## Layout

```
models/
  staging/         one row per source row, minimal cleanup
  intermediate/    joins, rolling windows, feature precomputes
  marts/           gold layer, the canonical truth
  reconciliation/  streaming alerts joined to canonical truth
```

## Running

```bash
cd batch/dbt_project
cp profiles.example.yml ~/.dbt/profiles.yml    # first time only
dbt deps
dbt build                   # run models + tests
dbt build --select staging+ # staging plus downstream
```

## Tests

Every model gets `not_null` and `unique` tests on its grain keys. Cross-model
referential tests live under `tests/`. These are non-optional; a PR that
drops a test is a PR that loses its sign-off.
