# AWS Deployment Release Discipline PRD

## Problem Statement

AlphaDB AWS deploys can spend minutes rolling both the public Cockpit service
and private AlphaDB API service even when only one image effectively changed.
The current timestamp-tag behavior makes every normal deploy look new to AWS,
post-deploy validation pays repeated Fargate task startup overhead, and runtime
paths still have opportunities to run Operational State DDL during live request
or worker execution.

The operator needs deploys that are faster, easier to reason about, and safer to
eventually initiate from Cockpit without blurring the boundary between deploying
workers and granting live trading authority.

## Solution

Make the AWS deployment path content-addressed and release-oriented.

Cockpit and Python runtime images should use deterministic build-context hashes
as their default image tags. Existing matching ECR tags should be reused unless
the operator explicitly forces a rebuild. The Cockpit stack should avoid
unnecessary API-to-Cockpit service serialization and use health-check settings
that fit the single-operator MVP. Deployment validation should run as one
release-check task that owns migrations, runtime-config seeding, readiness
evidence, and smoke checks.

This keeps the current local operator path while laying the control-plane
foundation for a future Cockpit deployment workspace:

```text
Cockpit -> AlphaDB API -> Operational State deployment intent -> deployment worker -> AWS
```

## User Stories

1. As the AlphaDB operator, I want unchanged Cockpit image content to keep the same image tag, so that a backend-only deploy does not roll Cockpit.
2. As the AlphaDB operator, I want unchanged Python runtime image content to keep the same image tag, so that a frontend-only deploy does not roll the AlphaDB API or workers.
3. As the AlphaDB operator, I want the deploy plan to show image context hashes, so that I can see why a service will or will not roll.
4. As the AlphaDB operator, I want an explicit force-rebuild path, so that I can refresh base images without changing source.
5. As the AlphaDB operator, I want existing ECR content-hash tags reused, so that repeat deploys avoid unnecessary Docker build and push work.
6. As the AlphaDB operator, I want Cockpit and AlphaDB API service updates to stabilize independently, so that one service does not serialize the other without a real dependency.
7. As the AlphaDB operator, I want faster Cockpit target-group health checks, so that a healthy replacement task is accepted quickly.
8. As the AlphaDB operator, I want shorter Cockpit deregistration delay for the MVP, so that single-operator rollouts do not wait on long draining defaults.
9. As the AlphaDB operator, I want one deployed release-check task, so that migrations, readiness seeding, and smoke do not each pay Fargate startup overhead.
10. As the AlphaDB operator, I want migrations protected by an advisory lock, so that concurrent deploy/runtime starts cannot race on DDL.
11. As the AlphaDB operator, I want runtime paths to read readiness state rather than run migrations, so that request and worker execution stay fail-closed.
12. As the AlphaDB operator, I want the fallback script to follow the same release semantics, so that recovery work does not reintroduce timestamp rollouts.
13. As a future Cockpit user, I want deployment actions to become recorded backend intents, so that Cockpit can control deploys without receiving AWS credentials.
14. As a future Cockpit user, I want worker deployment and live-authority enablement represented as explicit deployment-intent fields, so that the MVP can request both while preserving auditability.
15. As an AFK agent, I want the release-discipline rules documented in one PRD and ADR, so that later slices do not rediscover the same tradeoffs.

## Implementation Decisions

- Keep the `cockpit` deployment surface as the public Cockpit plus private AlphaDB API stack.
- Make image identity content-addressed inside that surface.
- Hash the Cockpit Docker build context separately from the Python runtime build context.
- Include the target platform in image context hashes.
- Reuse existing ECR tags by default and require an explicit force rebuild to replace them.
- Keep the orchestrator as the canonical path and the shell script as recovery fallback.
- Replace three API one-off tasks with a single release-check command.
- Keep public Cockpit smoke separate from the release-check task because it verifies the ALB and browser-facing auth/proxy path.
- Protect Operational State migrations with a transaction-scoped Postgres advisory lock.
- Move request/runtime config status checks toward read-only schema/config readiness behavior.
- Keep future Cockpit deployment control behind AlphaDB API and a deployment worker, not direct frontend AWS calls.
- Follow ADR 0005 for Cockpit deployment authority: the single-operator MVP is broadly permissive, including explicit live schedule/authority changes.

## Testing Decisions

- Test plan output and command construction without real AWS calls.
- Test image reuse behavior through the command-runner boundary.
- Test release-check command behavior as CLI/API-level behavior rather than by asserting implementation details.
- Test CloudFormation template expectations by inspecting the rendered template for public Cockpit, private AlphaDB API, faster health checks, no API-to-Cockpit service dependency, and rollback image outputs.
- Keep public smoke tests focused on auth, proxy, Postgres health, portfolio credential status, and fail-closed live-order guard.
- Use existing deployment tests as prior art for script and template checks.

## Out of Scope

- Cockpit UI for deployment control.
- Cockpit-held AWS credentials.
- CI/CD, GitHub Actions, blue/green, canary, or multi-user draining.
- Custom domain, TLS, ACM, or Route53.
- New OAuth, RBAC, or enterprise approval systems.
- Implementing Cockpit UI controls for live authority enablement in this release-discipline PRD.
- Refactoring every Operational State repository to remove migration calls in one PR.
- Splitting the Cockpit and AlphaDB API into separate CloudFormation stacks.

## Further Notes

The intended future is compatible with full Cockpit-driven strategy and worker
deployment control. Per ADR 0005, the single-operator MVP should be broadly
permissive: Cockpit may request all supported surfaces plus explicit live
schedule/authority changes. The safe shape is backend-mediated: Cockpit records
a deployment intent through AlphaDB API, a deployment worker executes the
orchestrator with explicit profile/surface/schedule policy, and Operational
State records evidence, rollback pointers, and confirmation decisions.
