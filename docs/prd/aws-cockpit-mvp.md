# AWS Cockpit MVP PRD

## Problem Statement

AlphaDB now has the right local target-platform shape: Cockpit is the Next.js
operator UI, AlphaDB API is the Python product API, and Operational State is
Postgres. AWS still exposes the legacy Python dashboard service as the public
operator surface. That deployment no longer matches the product boundary or the
local development path.

The operator needs one clean AWS migration that makes Cockpit the public UI
without turning Next.js into a backend, exposing the Python API publicly, or
changing live worker authority.

## Solution

Deploy the AWS Cockpit MVP as one clean cutover to the target boundary.

The public AWS operator URL serves the production-built Next.js Cockpit. The
Cockpit owns lightweight PIN and signed-cookie access for the public surface and
keeps browser API calls same-origin through `/api/alphadb/*`. The Cockpit server
proxies those calls to a private Python AlphaDB API ECS service through private
service discovery or service-to-service DNS.

The Python AlphaDB API remains the product API and Postgres owner. It may keep
the legacy Python HTML routes as a private compatibility surface, but those
routes are not exposed as the public operator UI. Managed Postgres remains an
existing private prerequisite. Live worker deployment and order-submission
authority are not changed by this PRD.

## User Stories

1. As the AlphaDB operator, I want the AWS public dashboard URL to open Cockpit, so that AWS matches the target product surface.
2. As the AlphaDB operator, I want one public operator URL, so that I do not need to decide between Python dashboard and Cockpit surfaces.
3. As the AlphaDB operator, I want browser API calls to use `/api/alphadb/*`, so that local and AWS behavior stay the same.
4. As the AlphaDB operator, I want Cockpit to proxy API calls privately, so that the browser never sees the private AlphaDB API hostname.
5. As the AlphaDB operator, I want Python AlphaDB API to remain separate from Cockpit, so that trading, state, replay, registry, and Postgres ownership stay in Python.
6. As the AlphaDB operator, I want the Python API service to be private, so that it is not exposed as a second public backend.
7. As the AlphaDB operator, I want Postgres reachable only by Python target-platform services and authorized workers, so that Next.js never has DB credentials.
8. As the AlphaDB operator, I want current live worker behavior untouched, so that dashboard migration does not change live trading authority.
9. As the AlphaDB operator, I want live orders to remain fail-closed in dashboard deployment checks, so that deployment cannot accidentally enable trading.
10. As the AlphaDB operator, I want the existing managed Postgres dependency reused, so that the MVP does not grow into database provisioning.
11. As the AlphaDB operator, I want migrations and readiness checks to run against the existing database, so that deployment proves the stack can use Operational State.
12. As the AlphaDB operator, I want a production-built Cockpit image, so that AWS does not run a development server.
13. As the AlphaDB operator, I want a separate Python AlphaDB API image, so that service boundaries stay clear.
14. As the AlphaDB operator, I want one deploy script, so that build, push, deploy, migration, and smoke are repeatable.
15. As the AlphaDB operator, I want one ECR repository with separate image tags, so that image setup stays small.
16. As the AlphaDB operator, I want secrets passed as AWS secret references, so that raw secrets are not passed through CLI args or logs.
17. As the AlphaDB operator, I want lightweight PIN and signed-cookie auth on Cockpit, so that MVP access control stays simple.
18. As the AlphaDB operator, I want no OAuth or RBAC in this migration, so that the work stays focused on deployment boundary.
19. As the AlphaDB operator, I want the legacy Python HTML UI private or unexposed, so that it does not confuse the public product path.
20. As the AlphaDB operator, I want no parallel public rollout, so that the MVP cuts directly to the target boundary.
21. As the AlphaDB operator, I want simple rollback by redeploying the prior image or stack shape, so that recovery is possible without blue/green machinery.
22. As the AlphaDB operator, I want focused smoke checks, so that readiness is proven without a full CI/CD system.
23. As the AlphaDB operator, I want the public Cockpit URL to return login or app shell successfully, so that the visible surface is alive.
24. As the AlphaDB operator, I want PIN login smoke-tested, so that AWS access behavior works before I rely on it.
25. As the AlphaDB operator, I want proxied `/api/alphadb/health` to reach Python API, so that the critical boundary is verified.
26. As the AlphaDB operator, I want Python API health to include Postgres reachability, so that the proxy path proves real state access.
27. As the AlphaDB operator, I want the current HTTP ALB URL kept for MVP, so that custom domain and TLS do not expand scope.
28. As the AlphaDB operator, I want AWS docs to converge on Cockpit, so that agents do not follow stale Python-dashboard deployment paths.
29. As an AFK agent, I want clear deployment inputs, so that I can run the script without guessing VPC, subnet, secret, or image values.
30. As an AFK agent, I want smoke output to be machine-readable enough to inspect, so that failed deployment steps are obvious.
31. As an engineer, I want private service discovery left as an implementation choice, so that the simplest AWS mechanism can be used.
32. As an engineer, I want broad AlphaDB API hardening out of scope, so that deployment work does not become backend redesign.
33. As an engineer, I want the Cockpit proxy contract preserved, so that future UI work does not add direct DB or trading logic.
34. As an engineer, I want current AWS Python-only dashboard docs marked deprecated or replaced, so that there is one canonical deployment path.
35. As a future maintainer, I want clear out-of-scope notes, so that live worker changes, TLS, CI/CD, and API refactors become separate issues.

## Implementation Decisions

- Deploy two logical ECS services: public Cockpit and private AlphaDB API.
- Keep one public operator URL. That URL serves Cockpit.
- Keep browser API calls same-origin through `/api/alphadb/*`.
- Configure Cockpit with a private AlphaDB API base URL in AWS. The exact private discovery mechanism is an implementation choice.
- Do not expose the AlphaDB API as a public ALB route or custom public domain.
- Keep Postgres private and reachable by Python target-platform services and authorized workers only.
- Use existing managed Postgres as prerequisite. Do not provision a new database in this PRD.
- Run migrations/readiness against the existing database before declaring deployment usable.
- Build Cockpit as a production Next.js service. Do not run `next dev` in AWS.
- Keep Python AlphaDB API as a separate production image.
- Use one deployment template for the Cockpit service, AlphaDB API service, public ALB, task definitions, target groups, security groups, logs, and secret wiring.
- Use one deploy script to build, tag, push, deploy, run migrations/readiness, and run smoke checks.
- Use one ECR repository with separate Cockpit and AlphaDB API image tags.
- Do not pass raw DB URL, PIN, or cookie secret through the deploy script. Use AWS secret references.
- Put lightweight PIN and signed-cookie auth at the public Cockpit surface for MVP.
- Do not add OAuth, RBAC, ALB auth, or approval flows.
- Let the Python service keep legacy HTML routes privately for MVP. Do not spend this PRD splitting an API-only Python command.
- Replace or clearly deprecate the current Python-only AWS dashboard path once Cockpit cutover lands.
- Keep the current HTTP ALB URL posture for MVP. Defer custom domain and TLS.
- Do not change live worker deployment, schedule, image, or order-submission authority.
- Avoid broad AlphaDB API hardening. Preserve only existing health/API behavior needed for deployment verification.
- Use simple image/service redeploy as rollback. Do not add blue/green, canary, traffic shifting, or parallel public Python UI.
- Do not add GitHub Actions CI/CD for this PRD.

## Testing Decisions

- Test external behavior, not implementation details.
- Deployment smoke should verify that the public Cockpit URL returns the login screen or app shell.
- Deployment smoke should verify PIN login and signed-cookie access when AWS auth env is configured.
- Deployment smoke should verify that Cockpit `/api/alphadb/health` reaches the private Python AlphaDB API.
- Deployment smoke should verify that the AlphaDB API reports Postgres reachable.
- Deployment smoke should verify that live-order guard remains fail-closed.
- Deployment smoke should fail clearly when the private API is unreachable from Cockpit.
- Template or script tests should verify required parameters and secret references are present without printing secret values.
- Existing deployment smoke tests and dashboard auth tests are prior art.
- Existing local Cockpit smoke is prior art for proving Cockpit-to-API-to-Postgres reachability.

## Out of Scope

- Live worker deployment, scheduling, or order-submission changes.
- Making target-platform live trading authoritative.
- New managed Postgres provisioning.
- New CI/CD or GitHub Actions workflow.
- Custom domain, TLS, ACM, or Route53.
- OAuth, RBAC, ALB auth, or new approval systems.
- Public AlphaDB API endpoint.
- Blue/green, canary, traffic shifting, or parallel public Python dashboard.
- Broad AlphaDB API hardening or route redesign.
- Splitting the Python command into API-only and legacy-HTML commands.
- Multi-user session/drain behavior.
- Fake data, fake Lab insights, or demo operational rows.

## Further Notes

This PRD intentionally optimizes for a single-operator MVP. The clean boundary
matters more than deployment polish: public Cockpit, private AlphaDB API,
private Operational State. The migration should feel like AWS catching up to
the local target-platform path, not like a second product architecture.
