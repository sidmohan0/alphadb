# Experiments

This tree holds public-safe experiment charters, configs, manifest examples,
decision records, and high-level summaries.

Do not commit raw vendor data, private generated datasets, production logs,
model binaries, credentials, exchange account records, or live strategy
configuration. Generated experiment artifacts belong under ignored roots such
as `research/` or `artifacts/`, with committed manifests referring to hashes,
counts, schemas, and stable private paths only.

Recommended shape for a research branch:

```text
experiments/<experiment-id>/
  README.md
  configs/
  templates/
  decisions/
```

If a local experiment needs `raw/`, `normalized/`, `derived/`, or `results/`
subdirectories under this tree, those paths are ignored by Git.
