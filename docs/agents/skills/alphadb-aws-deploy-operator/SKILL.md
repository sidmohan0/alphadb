---
name: alphadb-aws-deploy-operator
description: Use for AlphaDB AWS deployment management: Cockpit deploys, deployment intents, alphadb-deploy plan/apply, release-check, rollout, rollback, deployment worker evidence, and Linear deployment ticket updates.
metadata:
  short-description: Operate AlphaDB AWS deploys
---

# AlphaDB AWS Deploy Operator

Use this repo-specific skill when working on AlphaDB AWS deployment, Cockpit
deployment, deployment intents, release checks, rollout/rollback, or deployment
Linear tickets.

## Required Reading

Before acting, read only the relevant sections of:

- `CONTEXT.md`
- `docs/deployment/aws-dashboard.md`
- `docs/adr/0004-aws-release-discipline.md`
- `docs/adr/0005-cockpit-deployment-authority.md`
- `deploy/aws/deployment-profile.example.yaml`

For implementation work, also inspect the current code around:

- `src/alphadb/aws_deploy.py`
- `src/alphadb/deploy.py`
- `src/alphadb/deployment_intents.py`
- `src/alphadb/deployment_worker.py`

## Mode Selection

Pick the narrowest mode that satisfies the request:

- `audit`: read-only inspect docs, manifests, AWS evidence, code, or Linear state.
- `plan`: run `alphadb-deploy aws plan`; do not mutate AWS.
- `validate`: run focused tests, Docker builds, syntax checks, and plan dry runs.
- `apply`: run `alphadb-deploy aws apply` only after explicit user approval.
- `rollback`: use deployment manifests, previous task definitions, images, and
  schedule state; ask before mutation.
- `publish`: commit, push, open PR, and update Linear only after validation.

## Operating Rules

- Prefer `alphadb-deploy aws plan|apply`.
- Treat fallback scripts under `deploy/aws/` as recovery tools, not the primary path.
- Never invent default VPCs, subnets, AWS accounts, secret names, or raw secrets.
- Never put AWS credentials, database URLs, private keys, or raw secret values in
  deployment intents, manifests, PRs, issues, or docs.
- Cockpit may be broadly permissive for the single-operator MVP per ADR 0005,
  but AWS execution stays server-side through AlphaDB API, Operational State,
  and a deployment worker.
- Deploying code and enabling live authority are distinct intent fields, even
  when the MVP requests both in one confirmed action.
- Do not mutate real AWS unless the user explicitly asks for apply/rollback.
- Do not mark Linear deployment tickets done without merge/deploy evidence.

## Validation Defaults

For release-discipline or deployment-intent changes, prefer the lightest useful
set:

```bash
.venv/bin/pytest tests/test_aws_deploy_orchestrator.py tests/test_deploy.py -q
.venv/bin/pytest tests/test_deployment_intents.py tests/test_deployment_worker.py -q
.venv/bin/ruff check .
```

Add broader checks when Dockerfiles, Next.js, CloudFormation, or public Cockpit
behavior changes:

```bash
pnpm build
docker build --platform linux/arm64 -t alphadb-validate:runtime .
docker build --platform linux/arm64 -t alphadb-validate:cockpit -f apps/dashboard/Dockerfile apps/dashboard
bash -n deploy/aws/deploy-cockpit-stack.sh
.venv/bin/alphadb-deploy aws plan --profile deploy/aws/deployment-profile.example.yaml --surfaces cockpit --skip-aws-read
```

If `pre-commit run --all-files` is unavailable or the repo has no
`.pre-commit-config.yaml`, report that explicitly.

## Handoff

Always summarize:

- selected mode and whether AWS was mutated
- surfaces involved
- deployment intent ids, manifest paths, and evidence status
- validation commands and results
- rollback pointers when available
- Linear tickets or PRs updated
