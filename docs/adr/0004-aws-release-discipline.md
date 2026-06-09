# AWS Deployment Uses Content-Addressed Release Discipline

Accepted. AlphaDB AWS deployment will use content-addressed image identities,
explicit release checks, and service-level rollout evidence instead of treating
every apply as a timestamped full-stack rollout.

## Decision

The AWS deployment orchestrator should derive Cockpit and Python runtime image
tags from deterministic build-context hashes. If an image tag already exists in
ECR and the operator did not force a rebuild, the deploy path should reuse that
image rather than rebuilding and pushing another timestamped tag.

The Cockpit surface remains the deployment surface for the public Cockpit and
private AlphaDB API stack, but deploy decisions inside that surface should be
image-aware. Backend-only changes should not roll Cockpit, and frontend-only
changes should not roll the AlphaDB API. Future Cockpit-driven deployment
controls should create recorded deployment intents through the AlphaDB API and a
deployment worker. Cockpit should not hold AWS credentials; live schedule and
authority changes are allowed only when explicit in the recorded intent.

Release validation should be one explicit `alphadb-deploy release-check` task
that runs release-only migrations, runtime-config seeding, readiness evidence,
and smoke checks. Runtime and request paths should check readiness and fail
closed if schema or configuration is missing rather than running DDL as a side
effect.

## Rationale

Timestamp tags made AWS deployments look like meaningful service changes even
when image content had not changed. That burned single-operator deploy time,
created avoidable ECS rollouts, and obscured which surface actually changed.

Content-addressed image tags and explicit release checks preserve the existing
MVP simplicity while making the release path deterministic, auditable, and
eventually safe to trigger from Cockpit through backend deployment intents.

## Consequences

- Operators can still force a rebuild when refreshing base images or recovering
  from a bad cached image.
- The fallback Cockpit script should stay recovery-only and follow the same
  image identity and release-check semantics as the orchestrator.
- CloudFormation templates should avoid unnecessary service serialization and
  should use health-check timings appropriate for the single-operator MVP.
- Cockpit deployment authority is governed by ADR 0005. Deploying a worker and
  enabling live trading authority remain distinct intent fields, even when the
  MVP requests both in one confirmed deployment action.
