# Broad X Signal Expansion

Broad X/social signal expansion is out of scope for the current KXBTC15M research branch.

## Why this is out of scope

The first real X API counts evaluation produced a cheap, auditable dataset, but raw trailing-count features made the baseline model worse across holdout Brier score, log loss, ROC AUC, and average precision. That result does not prove X can never matter, but it does show that broad count-volume and metadata expansion is not the fastest path to better model evidence.

Future X work should be scoped as materially different event-shock, spike, sparse-alert, or other high-signal features with explicit evidence. It should not restart broad raw-count ablations or general X News metadata collection by default.

## Prior requests

- ALP-65 - Add X signal ablations to model-evaluation reports
- ALP-68 - Add optional X News metadata companion features
