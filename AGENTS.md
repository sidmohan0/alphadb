# AGENTS.md

## Context

Read `CONTEXT.md` before making product or architecture changes. This repo is the fresh AlphaDB target-platform workspace, separate from the current Kalshi MVP repo.

## Agent skills

### Issue tracker

Issues and PRDs live in Linear under the ThreadFork `ALP` team. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five-role triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo: read `CONTEXT.md` and root `docs/adr/`. See `docs/agents/domain.md`.

## Working rules

- Preserve the target-platform/MVP boundary: this repo may define the future platform, but it must not assume control of the current live MVP.
- Prefer small, independently testable modules.
- Keep secrets and generated data out of Git.
- Use normal engineering branch prefixes such as `feat/`, `fix/`, `chore/`, and `docs/`.
