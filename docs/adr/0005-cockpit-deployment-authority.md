# Cockpit Deployment Authority Is Broadly Permissive for the MVP

Accepted. The single-operator MVP should allow Cockpit to request and approve
deployment actions broadly, including worker and live schedule changes, while
keeping AWS credentials and execution server-side.

## Decision

Cockpit deployment control should use this authority path:

```text
Cockpit -> AlphaDB API -> Operational State deployment intent -> deployment worker -> AWS
```

For the MVP, Cockpit may request all supported deployable surfaces, including
`cockpit`, `brti-collector`, `fair-value`, future strategy workers, future
runtime workers, and config-only strategy changes. Deployment intents may also
request live schedule or live-authority changes when those changes are explicit
in the intent.

The approval model is intentionally lightweight: an authenticated single
operator or supervised agent action may submit a deployment intent after an
explicit confirmation step. The MVP should not add RBAC, multi-party approval,
OAuth, enterprise workflow, or CI/CD machinery before the operator loop proves
value.

The firm boundary is execution location. Cockpit must not hold AWS credentials
or run AWS mutations from browser code. The AlphaDB API records and validates the
intent, Operational State stores audit/evidence, and a deployment worker executes
the AWS change using server-side credentials.

## Rationale

AlphaDB's current deployment work is for a single operator using disposable MVP
capital. The useful product loop is full end-to-end control from Cockpit:
deploy the UI, API, collectors, strategy workers, runtime configs, and live
schedule state from one place. Overly cautious authorization gates would slow
the MVP before there is enough usage to justify them.

The right MVP guardrail is not restrictive authorization. It is explicit intent,
operator confirmation, durable audit evidence, rollback pointers, release
checks, smoke evidence, and existing runtime fail-closed order/risk behavior.

## Consequences

- Cockpit deployment controls may include live schedule enable/disable/preserve
  actions when the intent names them explicitly.
- Deploying code and granting live authority remain distinct fields in the
  intent, but the MVP may request both in one confirmed deployment action.
- Agents may request deployment intents when operating under the authenticated
  Cockpit/API control plane.
- The deployment worker owns AWS credentials and AWS mutation calls.
- Future multi-user, RBAC, CI/CD, blue/green, or approval-workflow hardening is
  deliberately deferred until the MVP operator loop proves it needs those tools.
