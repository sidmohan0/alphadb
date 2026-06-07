# AGENTS.md

## Purpose

This file is the default operating guide for coding agents working in AlphaDB.

AlphaDB is the target-platform repo for a reusable Kalshi prediction-market trading platform. It is separate from the current live Kalshi MVP repo. Preserve that boundary unless the user explicitly scopes a cutover or integration task.

## Read first

Before product, architecture, strategy, model, risk, runtime, or data-model changes, read:

- `CONTEXT.md`
- `docs/adr/`
- relevant docs under `docs/architecture/`, `docs/strategy/`, `docs/deployment/`, or `docs/settlement/`

For small repo-structure, docs, hygiene, or template changes, read this file first and use `CONTEXT.md` only as needed.

## Default working rules

- Prefer small, reviewable, independently testable changes.
- Do not reorganize existing platform modules unless explicitly requested.
- Preserve the target-platform / Current MVP boundary.
- Keep secrets, credentials, private datasets, production logs, model binaries, generated data, and live account/order/fill artifacts out of Git.
- Prefer truthful sparse states over fake demo data.
- Do not introduce heavy frameworks unless explicitly requested.
- Do not expand MVP security scope unless explicitly requested.
- Run the lightest relevant validation before handing off.

## Branch taxonomy

Use the branch prefix that matches the intent of the work:

- `feat/...` for platform or product features.
- `fix/...` for bug fixes.
- `chore/...` for maintenance, dependencies, repo hygiene, or structure.
- `docs/...` for documentation-only work.
- `analysis/...` for exploratory data or system understanding without a formal hypothesis.
- `spike/...` for technical feasibility tests.
- `exp/...` for hypothesis-driven research experiments.

Examples:

- `chore/research-operating-structure`
- `exp/fill-probability-baseline`
- `analysis/aws-training-costs`
- `spike/vectorized-replay`
- `feat/aws-training-runner`
- `fix/db-connection-pooling`

## Research artifact policy

The public repo may include:

- templates
- synthetic fixtures
- sanitized examples
- artifact manifests
- public-safe reference notebooks
- high-level experiment summaries that do not reveal proprietary edge

The public repo must not include:

- credentials or `.env` files
- private keys or exchange secrets
- raw licensed market data
- raw official BRTI data
- private generated research datasets
- production database dumps
- live account, order, fill, or strategy logs
- model binaries
- proprietary thresholds or live strategy configs

When unsure, commit a manifest, schema, or synthetic fixture instead of the raw artifact.

## Research workflow

Use:

- `experiments/` for hypothesis, config, manifest, result, and decision records.
- `notebooks/` for curated public-safe notebooks.
- `notebooks/00_scratch/` for local disposable exploration; do not commit scratch notebooks by default.
- `db/queries/research/` for reusable research SQL.
- `db/queries/app/` for SQL used by app/platform paths.
- `src/alphadb/research/` for reusable research helpers that have not yet graduated into platform modules.

Promotion path:

```text
scratch notebook
  -> curated notebook
  -> experiment record
  -> research helper
  -> platform module
```

Promote reusable code out of notebooks and into Python modules when it becomes repeated or important.

## Strategy, model, and risk changes

Before changing strategy, model, or risk logic, create or update a short strategy diagnosis note unless the user explicitly asks for a direct implementation-only change.

Emergency live-risk actions such as pause, stop, disabling live orders, or reducing exposure are exempt. See:

- `docs/agents/strategy-diagnosis.md`

## Agent skills and docs

- Issues and PRDs live in Linear under the ThreadFork `ALP` team. See `docs/agents/issue-tracker.md`.
- Use the default five-role triage vocabulary. See `docs/agents/triage-labels.md`.
- For domain vocabulary, read `CONTEXT.md` and `docs/agents/domain.md`.

## Validation expectations

For most small PRs, run the smallest relevant set of checks:

```bash
pytest
alphadb-repo-hygiene
pre-commit run --all-files
```

If a command is unavailable or too broad for the scoped change, say so in the handoff and explain what was run instead.
