# AlphaDB Live-Money Cutover Checklist

This checklist is the ALP-157 operator plan for moving live-money authority from
the current MVP path to the AlphaDB dashboard-owned fair-value live path. It is
an evidence template and sequencing guard; it does not by itself authorize live
deployment, live config changes, schedule changes, or order submission.

## Control-Plane Rule

- Non-secret fair-value live runtime config comes only from the AlphaDB
  dashboard and its managed Postgres `live_runtime_configs` revisions.
- The dashboard-owned values are `max_order_dollars`,
  `max_market_exposure_dollars`, `max_daily_loss_dollars`, `min_edge`,
  `min_contract_price`, and `max_markets`.
- Secrets and infrastructure config stay outside the dashboard: `DATABASE_URL`,
  Kalshi API credentials, private keys, dashboard PIN/cookie secret, VPC,
  subnets, security groups, image tags, IAM roles, log groups, and schedules.
- CloudFormation parameters, task environment variables, Secrets Manager values,
  and CLI flags must not override dashboard-owned live runtime knobs for the
  AWS live worker. The task may carry CLI fallback defaults for local/fixture
  paths, but `--runtime-config-source postgres` makes the dashboard/Postgres
  revision authoritative in AWS.

## AWS Assumptions

- AWS profile: `alphadb`.
- AWS account observed during ALP-157 inventory: `766780331843`.
- Region: `us-east-2`.
- Kalshi production endpoint DNS should be rechecked before final cutover using
  the commands in `docs/deployment/aws-dashboard.md`.

## Target AlphaDB Resources

- Dashboard stack: `alphadb-dashboard`.
- Dashboard CloudWatch log group: `/ecs/alphadb-dashboard`.
- Dashboard URL/access path: `DashboardUrl` output from the
  `alphadb-dashboard` stack.
- Dashboard task secret source: `DatabaseUrlSecretArn`, expected to resolve to
  the managed Postgres `DATABASE_URL`.
- Live worker stack: `alphadb-fair-value-live`.
- Live worker EventBridge rule: `alphadb-fair-value-live`.
- Live worker ECS cluster: `alphadb-fair-value-live`.
- Live worker task definition family: `alphadb-fair-value-live`.
- Live worker CloudWatch log group: `/ecs/alphadb-fair-value-live`.
- Live worker manifest prefix:
  `s3://alphadb-artifacts-766780331843-us-east-2/fair-value-live/`.
- BRTI collector stack: `alphadb-brti-live-collector`.
- BRTI collector ECS service/cluster/task family:
  `alphadb-brti-live-collector`.
- BRTI collector CloudWatch log group:
  `/ecs/alphadb-brti-live-collector`.
- Expected manual-run path: `aws ecs run-task` against the
  `alphadb-fair-value-live` task definition, private or egress-capable subnets,
  and the live worker security group.
- Expected scheduled-run path: EventBridge rule `alphadb-fair-value-live`, kept
  `DISABLED` until the one-cycle smoke gate passes, the legacy path is paused,
  dashboard config is saved, and the operator explicitly approves the
  live-money enablement.

## Legacy MVP Resources To Pause

The legacy MVP live authority discovered in this AWS account is:

- Stack: `alphadb-structural-live`.
- EventBridge rule: `alphadb-structural-live`.
- ECS cluster: `alphadb-structural-live`.
- ECS task definition family: `alphadb-structural-live`.
- CloudWatch log group: `/ecs/alphadb-structural-live`.

Before AlphaDB becomes the only live-money runner, confirm the EventBridge rule
`alphadb-structural-live` is `DISABLED` and no `RUNNING` or `PENDING` ECS tasks
exist in the `alphadb-structural-live` cluster. Do not delete the stack, task
definition, log group, credentials, or artifacts during cutover; those are the
rollback/reference path.

## Intended Dashboard-Owned Runtime Config

Use the dashboard Live workspace and one Save action to create the active config
revision for first cutover:

| Knob | Intended value |
| --- | ---: |
| Max order dollars | `5.00` |
| Max market exposure dollars | `5.00` |
| Max daily loss dollars | `50.00` |
| Min edge | `0.00` |
| Min contract price | `0.25` |
| Max markets | `20` |

If the operator chooses different values, record the exact difference in the
evidence notes before enabling the AlphaDB worker.

## Required Evidence

Capture these items before calling the cutover complete:

- Dashboard reachability: `DashboardUrl`, login result, `/healthz`, and
  `/api/live` or visible Live workspace confirmation.
- Deployment smoke result: `alphadb-deploy migrate`, `alphadb-deploy smoke`,
  dashboard startup logs, and active runtime config read result.
- Shared Postgres source: dashboard stack `DatabaseUrlSecretArn`, live worker
  stack `DatabaseUrlSecretArn`, and confirmation they are the same secret/source.
- Saved config revision: `config_id`, `version`, `created_at`, prior rollback
  revision, and exact non-secret snapshot.
- Worker logs: CloudWatch stream name, run id, runtime guard result, and explicit
  evidence that `runtime_config.source` is `dashboard_postgres`.
- Worker manifest: S3 URI, `runtime_config.config_id`,
  `runtime_config.version`, `runtime_config.source`, and exact
  `runtime_config.snapshot`.
- One-cycle smoke evidence JSON validated by
  `scripts/validate-fair-value-live-smoke.py`, proving:
  `p95_runtime_seconds < 45`, `overlapping_task_count = 0`,
  `stale_task_count = 0`, `max_quote_age_seconds <= 15`,
  `min_contract_price = 0.25`, `min_edge = 0`,
  `task_definition_one_cycle = true`, `live_order_guards_preserved = true`, and
  `schedule_state_before = DISABLED`.
- BRTI-primary smoke evidence JSON validated by
  `scripts/validate-brti-primary-live-smoke.py`, proving: collector service
  desired/running count, CloudWatch log group, raw BRTI event insertion, latest
  context update, fresh `brti_latest_contexts` status, one fair-value cycle with
  `market_context_source=brti_primary`, recorded BRTI external-close evidence
  or a clean `brti_context_*` skip, unchanged fair-value and
  `expensive_yes_live` schedule state during smoke, preserved live-order guards,
  shared `DATABASE_URL` secret, manifest/status evidence location, and a
  rollback command back to `coinbase_primary`.
- Orders/fills/no-fills/skips: order ids or client order ids where available,
  fill counts, no-fill rows, explicit skip reasons, and any exchange/API error.
- Live status projection: dashboard latest-run summary and recent attempts after
  the worker run.
- Single-authority state: legacy MVP rule remains disabled, AlphaDB rule state is
  the intended state, and no unintended live-money runner is active.
- Rollback readiness: prior dashboard config revision, previous image/task
  definition, schedule disable command, and legacy restoration command.

## Cutover Sequence

1. Record current AWS state:
   - `aws --profile alphadb --region us-east-2 sts get-caller-identity`
   - `aws --profile alphadb --region us-east-2 events describe-rule --name alphadb-structural-live`
   - `aws --profile alphadb --region us-east-2 events describe-rule --name alphadb-fair-value-live`
   - `aws --profile alphadb --region us-east-2 ecs list-tasks --cluster alphadb-structural-live --desired-status RUNNING`
   - `aws --profile alphadb --region us-east-2 ecs list-tasks --cluster alphadb-fair-value-live --desired-status RUNNING`
2. Deploy the Cockpit/AlphaDB API and live worker wiring with both using the
   same managed Postgres `DATABASE_URL` secret/source.
3. Apply migrations and smoke checks from the deployed environment.
4. Open the Cockpit Live workspace and save the intended runtime config.
5. Verify the previous config revision is visible as the rollback target.
6. Ask for explicit operator confirmation before pausing or changing live-money
   authority.
7. Pause the legacy MVP rule `alphadb-structural-live` and verify no legacy
   runner can submit live orders automatically.
8. Run manual one-cycle smoke while `alphadb-fair-value-live` remains
   `DISABLED`.
9. Write smoke evidence JSON and validate it:
   - `scripts/validate-fair-value-live-smoke.py <evidence.json>`
10. Ask for explicit operator confirmation before enabling or triggering the
   scheduled AlphaDB live worker.
11. Enable the one-minute schedule only by deploying CloudFormation with
   `SCHEDULE_STATE=ENABLED FAIR_VALUE_LIVE_SMOKE_EVIDENCE=<evidence.json>`.
   The deploy script refuses to enable without passing evidence.
12. Verify the worker manifest records the dashboard config id/version/source and
    exact snapshot.
13. Verify the dashboard Live workspace shows the curated latest-run summary.
14. Complete the ALP-162 evidence handoff and only then mark ALP-156 complete.

## ALP-258 BRTI Primary Extension

Deploy the BRTI collector as its own restartable ECS service:

```bash
deploy/aws/deploy-brti-live-collector.sh
```

The collector service uses the same `alphadb/dashboard/database-url` secret as
the dashboard and fair-value live worker, reads the existing Kalshi WebSocket
credential secrets, emits CloudWatch lifecycle/observation logs, and does not
set live-order submission environment variables.

After the collector is stable and fresh BRTI latest context exists, flip the
dashboard-owned fair-value runtime config from the deployed image:

```bash
alphadb-runtime set-market-context --source brti_primary --created-by alp-258
```

Run a one-cycle fair-value live smoke with the fair-value EventBridge rule state
unchanged. Validate the combined BRTI evidence:

```bash
scripts/validate-brti-primary-live-smoke.py <brti-smoke-evidence.json>
```

BRTI rollback is config-only for fair value; the collector may keep running for
diagnostics and forward capture:

```bash
alphadb-runtime set-market-context --source coinbase_primary --created-by rollback-alp-258
```

## Rollback

- Restore prior config: use the dashboard/API to save the prior revision snapshot
  as the new active config.
- Stop AlphaDB authority: disable EventBridge rule `alphadb-fair-value-live` and
  stop any active `alphadb-fair-value-live` ECS tasks.
- Restore previous AlphaDB deploy: redeploy the prior image or task definition
  for `alphadb-dashboard` and/or `alphadb-fair-value-live`.
- Restore legacy authority only if the cutover is aborted and an operator
  explicitly approves it: re-enable `alphadb-structural-live` or redeploy the
  prior `alphadb-structural-live` stack configuration.

## ALP-157 Inventory Note

Read-only inventory on 2026-06-04 found `alphadb-fair-value-live` already
`ENABLED` with live-order guards true and CLI/env cap values instead of
dashboard/Postgres runtime config. A reversible safety pause was applied: the
EventBridge rule `alphadb-fair-value-live` is now `DISABLED`, and no
`RUNNING`/`PENDING` tasks remained in the cluster after verification. Evidence
from the pre-pause state includes:

- S3 prefix:
  `s3://alphadb-artifacts-766780331843-us-east-2/fair-value-live-fresh-20260604T194926Z/`
- Example run id: `fv_live_20260604T221440Z`.
- Manifest evidence: `submit_live_orders=true`,
  `runtime_guard.can_submit_live_orders=true`, `orders_placed=0` for that run,
  and no `runtime_config` id/version/source because the deployed task definition
  used CLI/env caps.
- Reconciliation evidence up to that run: `122` attempts, `60` submitted,
  `28` filled, `94` no-fill, and `net_pnl_dollars=7.7069`.

Treat that pre-pause state as incident evidence, not as valid ALP-156 cutover
evidence.

## ALP-161/ALP-162 Cutover Evidence

Evidence captured on 2026-06-04 after explicit operator confirmation:

- Dashboard URL:
  `http://alphadb-dashboard-1257882261.us-east-2.elb.amazonaws.com`.
- Dashboard stack: `alphadb-dashboard`, `CREATE_COMPLETE`, desired/running
  service count `1/1`.
- Live worker stack: `alphadb-fair-value-live`, `UPDATE_COMPLETE`.
- Shared runtime config source: both dashboard and live worker use
  `DatabaseUrlSecretArn`
  `arn:aws:secretsmanager:us-east-2:766780331843:secret:alphadb/dashboard/database-url-mFfgPh`.
- Active dashboard-owned runtime config:
  `live_cfg_13a290431e09`, version `2`, source `dashboard_postgres`.
- Active runtime config snapshot:
  `max_order_dollars=5.0`, `max_market_exposure_dollars=5.0`,
  `max_daily_loss_dollars=50.0`, `min_edge=0.0`,
  `min_contract_price=0.25`, `max_markets=20`.
- Rollback config revision: `live_cfg_78f1e41076ef`, version `1`.
- Patched live worker image:
  `766780331843.dkr.ecr.us-east-2.amazonaws.com/alphadb-dashboard:b0c68c6-alp161-skip-20260604230256`.
- Live worker task definition: `alphadb-fair-value-live:5`.
- Live worker command includes `--runtime-config-source postgres` and
  `--submit-live-orders`; it does not pass non-secret live cap values as CLI
  flags.
- Worker live-order guard evidence:
  `runtime_guard.can_submit_live_orders=true`,
  `credentials_present=true`, `explicit_live_enabled=true`,
  `human_cutover_approved=true`, `runtime_mode=gated-live`.
- Manual ALP-161 run:
  `fv_live_20260604T230533Z`.
- Manual run manifest:
  `s3://alphadb-artifacts-766780331843-us-east-2/fair-value-live/fv_live_20260604T230533Z/manifest.json`.
- Manual run outcome: one live IOC order submitted and filled for
  `KXBTC15M-26JUN041915-15`; order id
  `6abb0f79-3763-4356-8925-66a551da1453`, client order id
  `fv_0260604T230533Z_ead7f272f3`, side `no`, filled contracts `13`,
  max loss/exposure `4.7571`.
- Manual run manifest records `runtime_config.config_id=live_cfg_13a290431e09`,
  `runtime_config.version=2`, `runtime_config.source=dashboard_postgres`, and
  the exact dashboard snapshot above.
- Manual run dashboard projection: `/api/live` reported
  `live_status.run_id=fv_live_20260604T230533Z`, decision `submitted`,
  fill status `filled`, recent attempt count `1`.
- Recurring AlphaDB live runner was enabled through CloudFormation with
  `ScheduleState=ENABLED`, `ScheduleExpression=rate(1 minute)`.
- First scheduled run:
  `fv_live_20260604T230914Z`.
- First scheduled run manifest:
  `s3://alphadb-artifacts-766780331843-us-east-2/fair-value-live/fv_live_20260604T230914Z/manifest.json`.
- First scheduled run outcome: explicit skipped attempt with reason
  `market_exposure_cap_reached`, proving the dashboard-owned
  `max_market_exposure_dollars=5.0` cap blocked an additional order after the
  manual fill.
- Latest observed dashboard projection after schedule enablement:
  `live_status.run_id=fv_live_20260604T231005Z`, decision `skipped`, reason
  `market_exposure_cap_reached`, config id `live_cfg_13a290431e09`, config
  version `2`.
- Single-authority state:
  `alphadb-fair-value-live` EventBridge rule `ENABLED`;
  `alphadb-structural-live` EventBridge rule `DISABLED`; no legacy
  `RUNNING`/`PENDING` ECS tasks observed after enablement.
- Local regression check after explicit-skip patch:
  `.venv/bin/pytest tests/test_fair_value_mvp.py tests/test_live_runtime.py tests/test_deploy.py -q`
  returned `32 passed`.

The explicit-skip patch was required because the first manual run
`fv_live_20260604T225944Z` exited successfully and recorded the dashboard
config, but it produced an empty `live_order_attempts.json` when replay emitted
no order. The patched worker records replay skips and cap skips as live attempt
rows so the dashboard and evidence handoff always show an auditable submitted,
no-fill, or skipped outcome.

## Dashboard Fact Audit 2026-06-04T23:33Z

The dashboard was patched so visible live status comes from the persisted live
worker projection, not the dashboard web process guard.

- Deployed dashboard image:
  `766780331843.dkr.ecr.us-east-2.amazonaws.com/alphadb-dashboard:b0c68c6-dashboard-live-only-api-20260604233005`.
- Dashboard ECS task definition: `alphadb-dashboard:6`, desired `1`, running
  `1`, rollout `COMPLETED`.
- Dashboard web task environment: `ALPHADB_RUNTIME_MODE=gated-live`,
  `ALPHADB_ENABLE_LIVE_ORDERS=0`, `ALPHADB_HUMAN_CUTOVER_APPROVED=0`. The
  dashboard service has no live-order credentials; the live worker is the only
  process authorized to submit orders.
- Local regression check:
  `.venv/bin/pytest tests/test_dashboard_live_console.py tests/test_dashboard_auth.py tests/test_deploy.py -q`
  returned `22 passed`.
- Authenticated dashboard check returned login HTTP `303`, `health.ok=true`,
  and environment `aws`.
- HTML check found none of: `live orders disabled`, `runtime_guard`,
  `Research`, `Registry`, `Artifacts`, `paper`, `shadow`, `fixture`, `mock`,
  or `simulated`.
- `/api/live` check found `api_has_runtime_guard=false`,
  `live_status_has_summary=false`, and `api_shadow_terms_present=false`.
- Active dashboard config shown by `/api/live`:
  `live_cfg_13a290431e09`, version `2`, `max_order_dollars=5.0`,
  `max_market_exposure_dollars=5.0`, `max_daily_loss_dollars=50.0`,
  `min_edge=0.0`, `min_contract_price=0.25`, `max_markets=20`.
- Latest dashboard live status observed:
  `fv_live_20260604T233310Z`, config id `live_cfg_13a290431e09`, config
  version `2`, `live_orders_enabled=true`, market
  `KXBTC15M-26JUN041945-45`, decision `submitted`, attempt status
  `submitted`, fill status `no_fill`.
- Matching S3 manifest:
  `s3://alphadb-artifacts-766780331843-us-east-2/fair-value-live/fv_live_20260604T233310Z/manifest.json`.
- Manifest source evidence:
  `config.source=kalshi-public`, `config.coinbase_source=coinbase-live`,
  `config.runtime_config_source=postgres`, `config.submit_live_orders=true`,
  `runtime_config.source=dashboard_postgres`,
  `runtime_controls.live_orders_enabled=true`,
  `runtime_controls.report_only=false`, and
  `runtime_controls.runtime_guard.paper_orders_allowed=false`.
- Matching live order attempt:
  order id `d4eb7b6c-aced-4806-b28a-082334b8e23d`, market
  `KXBTC15M-26JUN041945-45`, side `no`, status `submitted`, reason
  `submitted`, fill count `0`.
- Matching reconciliation:
  settlement status `partial`, unsettled exposure `$3.599`, latest matching
  order id `d4eb7b6c-aced-4806-b28a-082334b8e23d` settlement status
  `no_fill`.
- Single-authority check:
  `alphadb-fair-value-live` EventBridge rule `ENABLED`;
  `alphadb-structural-live` EventBridge rule `DISABLED`.
- Codex report automation:
  `Fair-value live 15m performance report`, status `ACTIVE`, schedule
  `FREQ=HOURLY;BYMINUTE=2,17,32,47`. The report prompt requires
  `live_reconciliation_report.json` reconciled figures: settlement status,
  settled/unsettled counts, filled contracts, gross cost, fees, payout, net PnL,
  unsettled exposure, and per-order/market reconciliation rows. The scheduled
  report entrypoint is the repo-owned `alphadb-fair-value-live-report` command,
  which accepts explicit `--start` and `--end` interval timestamps and reports
  AWS auth, DNS, endpoint, and per-surface read failures separately.

## ALP-162 Rollback Commands

Disable AlphaDB live-money authority:

```bash
aws --profile alphadb --region us-east-2 events disable-rule \
  --name alphadb-fair-value-live
aws --profile alphadb --region us-east-2 ecs list-tasks \
  --cluster alphadb-fair-value-live --desired-status RUNNING \
  --query 'taskArns[]' --output text \
  | xargs -n1 -r aws --profile alphadb --region us-east-2 ecs stop-task \
      --cluster alphadb-fair-value-live --task
```

Restore the prior dashboard-owned config by saving the version `1` snapshot in
the dashboard/API as a new active revision:

```json
{
  "max_order_dollars": 5.0,
  "max_market_exposure_dollars": 5.0,
  "max_daily_loss_dollars": 50.0,
  "min_edge": 0.0,
  "min_contract_price": 0.25,
  "max_markets": 20
}
```

Restore the previous live worker image/task definition if needed:

```bash
aws --profile alphadb --region us-east-2 cloudformation deploy \
  --stack-name alphadb-fair-value-live \
  --template-file deploy/aws/fair-value-live-trading-job.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ContainerImage=766780331843.dkr.ecr.us-east-2.amazonaws.com/alphadb-dashboard:b0c68c6-alp158-20260604222924 \
    ScheduleState=DISABLED
```

Restore legacy MVP authority only after explicit operator approval:

```bash
aws --profile alphadb --region us-east-2 events enable-rule \
  --name alphadb-structural-live
```
